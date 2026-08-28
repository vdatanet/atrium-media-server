#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""How may a client present a token, which routes require one, and how is a refusal shaped?

Feature 002 rests on the claims below. Most were first measured by hand, before or outside this
repository; the 2026-08-28 runs folded every one of 002's hand measurements into this script
(audit L2), so each is re-measured on every run. Each decides code that four tasks assert:

* **The five mechanisms** - `Authorization: MediaBrowser Token="..."`,
  `X-Emby-Authorization` carrying the same, `X-Emby-Token`, `?ApiKey=` and `?api_key=` -
  authenticate every authenticated route. All five are measured by this probe on every run, on an
  **image route and a delivery route** as well as an API one; the query forms exist because image
  loaders and media players are handed URLs and set no headers. Whether those two classes require
  a token at all is part of the question: a class that answers without one is not evidence that
  any mechanism works.

  **The second is why this list grew on 2026-08-28.** It entered by hand-measurement on
  2026-08-26, on an authenticated API route only, while behaviours section 2.4 read as though it
  had been measured everywhere. `mechanisms()` now sends it everywhere the other four go, which
  is the only way that sentence becomes true rather than expected.
* **The header grammar is lenient in six ways and strict in two** - whitespace around an `=`, or
  a lowercase component name, and nothing is read out of the header (behaviours section 2.12's
  table) - and **the scheme word is required**: `MediaBrowser` or `Emby`, compared
  case-insensitively, because with `Bearer`, a made-up word or no scheme at all the header is not
  read either. Measured as the token grammar on the API route, where "read" is a `200` and "not
  read" is a `401`. (These rows were hand-measured on 2026-08-26 and folded into this probe on
  2026-08-28 - the L2 pattern of docs/audits/2026-08-28.md.)
* **`DeviceId` is mandatory on `POST /Users/AuthenticateByName` and there only** - the same
  client header with no `DeviceId` is served normally on an ordinary authenticated route
  (behaviours section 2.13; the `400` half of that entry is the bullet below).
* **The sign-in response's one-off shapes** (002 spec sections 3.3, 3.5 and 3.6): the user
  object sends `Name` first and `ServerId` before `Id`; `Policy` carries 42 properties, with
  `-1` for `LoginAttemptsBeforeLockout` (a sentinel, not a count) and `0` for
  `MaxActiveSessions` (unlimited); `Configuration` carries 16; and a fresh session's
  `LastPlaybackCheckIn` is .NET's minimum date, not null and not absent. Under the CamelCase
  content profile the key conversion reaches *inside* `Policy` - `policy.isAdministrator` -
  which is what `compat/model.py`'s `PropertyKeyed` annotation reproduces.
* **`GET /Users/Public` answers a caller carrying no token with complete user objects** -
  `Policy` and `Configuration` included, equal to the authenticated view of the same user (002
  spec section 3.4; the disclosure argument is behaviours section 3.5).
* **A session's declared capabilities and the server's flags are different values** (002 spec
  section 3.8, behaviours section 2.14): `POST /Sessions/Capabilities/Full` answers `204` with
  no body, and the session then reports `SupportsMediaControl: false` and
  `SupportsRemoteControl: false` at the top level while echoing the declared `true` back inside
  `Capabilities`, with `PlayableMediaTypes` and `SupportedCommands` hoisted verbatim. An unknown
  property in the declaration is accepted at the door - the `204` - and **dropped** from the
  echo. (The 2026-08-26 hand-measurement saw only the `204` and wrote "kept"; the 2026-08-28
  run read the echo back and it is not, so Atrium's keep is a recorded divergence rather than
  parity.) A `SupportedCommands` value outside the reference's enum refuses the whole body with
  a `400` whose `errors` map names both the offending element's path (`$[0]`) and
  `capabilities` (behaviours section 5.1). Measured on a session this probe creates for itself
  and logs out afterwards.
* **A disabled user is refused with `403`, whether the password is right or wrong** - the status
  is the whole of the difference from an unknown username's `401`; the bodies are identical.
  (This bullet said `401` until the 2026-08-26 run measured `403` and the documents moved -
  behaviours section 2.11 carries the client argument. The expectation below matches the
  documents as corrected, so the probe flags a *change*, not the old hypothesis.)
* **A missing or unparseable client header is a `400`** - not a `401`, because a client reading
  it as one tells the user their password is wrong.
* **`AuthenticateByName` takes the client components in either header**, `X-Emby-Authorization`
  or `Authorization`. Nothing here had ever asked: every call this probe made set the Emby
  spelling, so the route's requirement was measured for one name and documented for both. A real
  tvOS client sends only `Authorization`, on every request including this one, and signs into real
  Jellyfin servers - third-party evidence, which is a lead and not a measurement
  (api-surface-v1.md section 3).
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
import contextlib
import json
import os
import re
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

#: .NET's minimum date, which is what a session that has never played anything reports as
#: `LastPlaybackCheckIn` - not null and not absent (002 spec section 3.3).
MIN_DATE = "0001-01-01T00:00:00.0000000Z"

#: The two fields of a user object that move with every request this probe makes, so the
#: /Users/Public-versus-authenticated comparison excludes them rather than racing its own
#: sign-ins.
VOLATILE_USER_FIELDS = {"LastActivityDate", "LastLoginDate"}

#: The session object's fields in the reference's order, for a session that is not playing
#: anything - src/atrium/api/sessions.py's "twenty-three fields" claim and the order
#: tests/golden/Sessions.json pins. `UserPrimaryImageTag` rides only when the user has an
#: avatar, so its absence is not a finding.
SESSION_FIELD_ORDER = [
    "PlayState",
    "AdditionalUsers",
    "Capabilities",
    "RemoteEndPoint",
    "PlayableMediaTypes",
    "Id",
    "UserId",
    "UserName",
    "Client",
    "LastActivityDate",
    "LastPlaybackCheckIn",
    "DeviceName",
    "DeviceId",
    "ApplicationVersion",
    "IsActive",
    "SupportsMediaControl",
    "SupportsRemoteControl",
    "NowPlayingQueue",
    "NowPlayingQueueFullItems",
    "HasCustomDeviceName",
    "ServerId",
    "UserPrimaryImageTag",
    "SupportedCommands",
]

OPTIONAL_SESSION_FIELDS = {"UserPrimaryImageTag"}


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
    read_limit: int = 4096,
) -> tuple[int, dict[str, str], bytes]:
    """One request, carrying nothing the caller did not ask for - no token is added behind our back.

    At most `read_limit` bytes of any response are read - 4 KB by default, which is what makes
    this safe to point at a delivery route: the socket closes after the first few bytes rather
    than downloading a film to learn a status code. The sign-in-body and session measurements
    raise it, because a full user object with 42 policy properties does not fit in 4 KB.
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
            return response.status, dict(response.headers), response.read(read_limit)
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read(read_limit)
    except urllib.error.URLError as exc:
        raise ProbeError(f"{method} {path} -> {exc.reason}") from exc


def authenticate(
    server: Server,
    username: str,
    password: str,
    header: str | None,
    header_name: str = "X-Emby-Authorization",
) -> Any:
    """POST /Users/AuthenticateByName with exactly the client header given, or none at all.

    `header_name` exists because the route accepts the components in either spelling and this
    probe had only ever sent one of them.
    """
    headers = {"Content-Type": "application/json"}
    if header:
        headers[header_name] = header
    body = json.dumps({"Username": username, "Pw": password}).encode("utf-8")
    return request(server, "POST", AUTHENTICATE, headers=headers, data=body, read_limit=1 << 20)


def mechanisms(token: str) -> list[tuple[str, dict[str, str], dict[str, str]]]:
    """The five ways a token may arrive, in the measured precedence order.

    specs/002 section 3.1 lists four. The fifth - `X-Emby-Authorization` carrying a `Token=` - was
    measured after that specification was accepted and lives in behaviours section 2.4; the
    specification still says four, which is an amendment somebody owes and not something this
    script can fix by omitting the row.
    """
    return [
        ("Authorization: MediaBrowser", {"Authorization": f'MediaBrowser Token="{token}"'}, {}),
        (
            "X-Emby-Authorization: MediaBrowser",
            {"X-Emby-Authorization": f'MediaBrowser Token="{token}"'},
            {},
        ),
        ("X-Emby-Token header", {"X-Emby-Token": token}, {}),
        ("?ApiKey= query", {}, {"ApiKey": token}),
        ("?api_key= query", {}, {"api_key": token}),
    ]


def grammar_variations(token: str) -> list[tuple[str, str, bool]]:
    """behaviours section 2.12's variation table, as the token grammar on the API route.

    Each row is (variation, the whole `Authorization` value, whether the reference reads it).
    A header the parser reads authenticates and answers `200`; one it does not read leaves the
    request tokenless, which is the `401` the two strict rows and the scheme-word rows measure.
    """
    return [
        ("values quoted (the baseline)", f'MediaBrowser Token="{token}"', True),
        ("values bare", f"MediaBrowser Token={token}", True),
        ("scheme Emby", f'Emby Token="{token}"', True),
        ("scheme in lowercase", f'mediabrowser Token="{token}"', True),
        ("extra spaces after the scheme", f'MediaBrowser    Token="{token}"', True),
        (
            "an unknown component alongside, order reversed",
            f'MediaBrowser Nonsense="x", Token="{token}"',
            True,
        ),
        (
            "no space after the comma",
            f'MediaBrowser Client="atrium-probe",Token="{token}"',
            True,
        ),
        (
            "a space before the comma",
            f'MediaBrowser Client="atrium-probe" , Token="{token}"',
            True,
        ),
        ("a trailing comma", f'MediaBrowser Token="{token}",', True),
        ("whitespace around the =", f'MediaBrowser Token = "{token}"', False),
        ("a lowercase component name", f'MediaBrowser token="{token}"', False),
        ("scheme Bearer", f'Bearer Token="{token}"', False),
        ("no scheme word at all", f'Token="{token}"', False),
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
    """The six requests that say whether a route class is authenticated, and by what.

    Returns `(refuses_without_a_token, all_five_authenticated)`. The first is measured rather than
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


def measure_signin_body(probe: Probe, disagreements: list[str], body: dict[str, Any]) -> None:
    """The one-off shapes of 002 spec sections 3.3 and 3.5, read from one fresh sign-in.

    The body arrives parsed and stays internal: it carries an access token, and nothing here
    prints a value - only key orders, counts, and the two documented sentinels.
    """
    user = body.get("User") or {}
    policy = user.get("Policy") or {}
    configuration = user.get("Configuration") or {}
    session = body.get("SessionInfo") or {}

    keys = list(user)
    name_first = keys[:1] == ["Name"]
    server_id_first = (
        "ServerId" in keys and "Id" in keys and keys.index("ServerId") < keys.index("Id")
    )
    probe.observe(
        "user object order",
        f"{'Name first' if name_first else 'first key ' + (keys[0] if keys else 'none')}; "
        f"ServerId {'before' if server_id_first else 'NOT before'} Id",
    )
    if not name_first:
        disagreements.append("the user object does not send Name first (002 spec section 3.5)")
    if not server_id_first:
        disagreements.append(
            "the user object does not send ServerId before Id (002 spec section 3.5)"
        )

    lockout = policy.get("LoginAttemptsBeforeLockout")
    cap = policy.get("MaxActiveSessions")
    probe.observe(
        "Policy",
        f"{len(policy)} properties; LoginAttemptsBeforeLockout {lockout!r}, "
        f"MaxActiveSessions {cap!r}",
    )
    if len(policy) != 42:
        disagreements.append(f"Policy carries {len(policy)} properties, not the measured 42")
    if lockout != -1:
        disagreements.append(
            f"LoginAttemptsBeforeLockout is {lockout!r}, not the -1 sentinel (002 spec section 3.5)"
        )
    if cap != 0:
        disagreements.append(f"MaxActiveSessions is {cap!r}, not the measured 0")

    probe.observe("Configuration", f"{len(configuration)} properties")
    if len(configuration) != 16:
        disagreements.append(
            f"Configuration carries {len(configuration)} properties, not the measured 16"
        )

    check_in = session.get("LastPlaybackCheckIn")
    probe.observe("fresh session LastPlaybackCheckIn", repr(check_in))
    if check_in != MIN_DATE:
        disagreements.append(
            f"a fresh session's LastPlaybackCheckIn is {check_in!r}, not .NET's minimum date "
            "(002 spec section 3.3)"
        )


def measure_capabilities(
    probe: Probe, server: Server, disagreements: list[str], token: str
) -> None:
    """002 spec section 3.8 and behaviours sections 2.14 and 5.1, on this probe's own session.

    The token is the fresh sign-in's, so everything posted here decorates a session this run
    created - and the section ends by logging that session out.
    """
    if not token:
        probe.note("the sign-in body carried no AccessToken; capabilities were not measured")
        return
    auth = {"X-Emby-Token": token, "Content-Type": "application/json"}
    declaration = {
        "PlayableMediaTypes": ["Video"],
        "SupportedCommands": ["Play"],
        "SupportsMediaControl": True,
        "AtriumProbeUnknownProperty": "kept",
    }
    status, _, resp = request(
        server,
        "POST",
        "/Sessions/Capabilities/Full",
        headers=auth,
        data=json.dumps(declaration).encode("utf-8"),
    )
    probe.observe("POST /Sessions/Capabilities/Full", f"{status}  {len(resp)}B body")
    if status != 204 or resp:
        disagreements.append(
            f"Capabilities/Full answered {status} with {len(resp)} bytes, not an empty 204"
        )

    status, _, sessions_body = request(
        server,
        "GET",
        "/Sessions",
        headers={"X-Emby-Token": token},
        params={"deviceId": PROBE_DEVICE},
        read_limit=1 << 20,
    )
    row: dict[str, Any] | None = None
    if status == 200:
        rows = json.loads(sessions_body)
        row = next((r for r in rows if r.get("DeviceId") == PROBE_DEVICE), None)
    if row is None:
        probe.note(
            f"GET /Sessions did not return this probe's session (status {status}); the "
            "echo-versus-flags claims were not measured"
        )
    else:
        expected_fields = [
            name
            for name in SESSION_FIELD_ORDER
            if name in row or name not in OPTIONAL_SESSION_FIELDS
        ]
        probe.observe(
            "session object",
            f"{len(row)} fields, "
            + ("in the documented order" if list(row) == expected_fields else "ORDER DIFFERS"),
        )
        if list(row) != expected_fields:
            disagreements.append(
                "the session object's fields are not the documented twenty-three in the "
                "reference's order (src/atrium/api/sessions.py, tests/golden/Sessions.json): "
                + ", ".join(row)
            )
        for name in ("PlayState", "Capabilities"):
            if not isinstance(row.get(name), dict):
                disagreements.append(
                    f"{name} is not an object on a session that has played nothing - "
                    "src/atrium/api/sessions.py records objects, not nulls"
                )
        caps = row.get("Capabilities") or {}
        top_media = row.get("SupportsMediaControl")
        top_remote = row.get("SupportsRemoteControl")
        kept = "AtriumProbeUnknownProperty" in caps
        probe.observe(
            "session top level",
            f"SupportsMediaControl {top_media}, SupportsRemoteControl {top_remote}",
        )
        probe.observe(
            "Capabilities echo",
            f"SupportsMediaControl {caps.get('SupportsMediaControl')}, unknown property "
            f"{'kept' if kept else 'DROPPED'}",
        )
        probe.observe(
            "hoisted verbatim",
            f"PlayableMediaTypes {row.get('PlayableMediaTypes')}, "
            f"SupportedCommands {row.get('SupportedCommands')}",
        )
        if top_media is not False or top_remote is not False:
            disagreements.append(
                "a session that declared SupportsMediaControl reports it at the top level - "
                "behaviours section 2.14 measured false there"
            )
        if caps.get("SupportsMediaControl") is not True:
            disagreements.append(
                "the declared SupportsMediaControl was not echoed back inside Capabilities"
            )
        if kept:
            disagreements.append(
                "an unknown property in the declaration came back inside Capabilities - the "
                "reference was measured dropping it, and Atrium's keep is the recorded "
                "divergence, not parity (002 spec section 3.8)"
            )
        if row.get("PlayableMediaTypes") != ["Video"] or row.get("SupportedCommands") != ["Play"]:
            disagreements.append(
                "PlayableMediaTypes or SupportedCommands were not hoisted to the top level "
                "verbatim (behaviours section 2.14)"
            )

    bad = dict(declaration, SupportedCommands=["AtriumProbeNotACommand"])
    status, _, refusal = request(
        server,
        "POST",
        "/Sessions/Capabilities/Full",
        headers=auth,
        data=json.dumps(bad).encode("utf-8"),
    )
    error_keys: list[str] = []
    if refusal:
        with contextlib.suppress(ValueError):
            error_keys = sorted(json.loads(refusal).get("errors") or {})
    probe.observe(
        "unknown SupportedCommands value", f"{status}, errors keyed {error_keys or 'none'}"
    )
    if status != 400 or error_keys != ["$[0]", "capabilities"]:
        disagreements.append(
            f"an unknown SupportedCommands value answered {status} with errors keyed "
            f"{error_keys}, not the measured 400 keyed $[0] and capabilities (behaviours "
            "section 5.1)"
        )

    status, _, _ = request(server, "POST", "/Sessions/Logout", headers={"X-Emby-Token": token})
    probe.observe("POST /Sessions/Logout (cleanup)", str(status))


def measure_public_users(probe: Probe, server: Server, disagreements: list[str]) -> None:
    """002 spec section 3.4 and behaviours section 3.5: /Users/Public sends everything.

    The comparison excludes the two activity timestamps, which this probe's own sign-ins move
    between the two requests being compared.
    """
    status, _, public_body = request(server, "GET", "/Users/Public", read_limit=1 << 20)
    if status != 200:
        disagreements.append(f"/Users/Public answered {status}, not 200")
        return
    rows = json.loads(public_body)
    mine = next((r for r in rows if r.get("Id") == server.user_id), None)
    complete = sum(1 for r in rows if {"Policy", "Configuration"} <= set(r))
    probe.observe(
        "/Users/Public, no token", f"{len(rows)} user(s), {complete} with Policy and Configuration"
    )
    if rows and complete != len(rows):
        disagreements.append(
            "/Users/Public rows no longer all carry Policy and Configuration - behaviours "
            "section 3.5 measured the complete object for every listed user"
        )
    if mine is None:
        probe.note(
            "this probe's user is not on /Users/Public (hidden from login screens?), so the "
            "identical-to-authenticated comparison was not measured; only the rows' completeness "
            "was."
        )
        return

    status, _, me_body = request(
        server,
        "GET",
        API_ROUTE,
        headers={"X-Emby-Token": server.token or ""},
        read_limit=1 << 20,
    )
    if status != 200:
        probe.note(f"GET {API_ROUTE} answered {status}; the comparison was not measured")
        return
    me = json.loads(me_body)
    public_keys = [k for k in mine if k not in VOLATILE_USER_FIELDS]
    authed_keys = [k for k in me if k not in VOLATILE_USER_FIELDS]
    differing = sorted(k for k in set(public_keys) | set(authed_keys) if mine.get(k) != me.get(k))
    probe.observe(
        "public row versus authenticated",
        "identical outside the activity timestamps"
        if not differing and public_keys == authed_keys
        else "differs on " + (", ".join(differing) or "key order alone"),
    )
    if differing or public_keys != authed_keys:
        disagreements.append(
            "/Users/Public and the authenticated user object differ on "
            + (", ".join(differing) or "key order")
            + " - 002 spec section 3.4 measured them identical"
        )


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
            "all five mechanisms authenticate every authenticated route, on an image and a "
            "delivery route as well as an API one; AuthenticateByName takes the client components "
            "in either header spelling; a disabled account is refused with 403 whether the "
            "password is right or wrong, its body identical to the unknown-username 401's; "
            "a missing or unparseable client header is a 400 rather than a 401; the header "
            "grammar is lenient in six measured ways and refuses whitespace around =, a "
            "lowercase component name, and any scheme word but MediaBrowser or Emby; a "
            "DeviceId-less client header is served normally outside AuthenticateByName; the "
            "sign-in body sends Name first and ServerId before Id, 42 policy properties with "
            "the -1 lockout sentinel and MaxActiveSessions 0, 16 configuration properties, and "
            "a minimum-date LastPlaybackCheckIn, the session object carrying its twenty-three "
            "fields in the reference's order; /Users/Public sends the complete user object "
            "to a caller with no token; and a session's declared capabilities are echoed and "
            "hoisted while the top-level control flags stay false, an unknown declaration "
            "property accepted at the door and dropped from the echo, and an unknown "
            "SupportedCommands value refusing the whole body with a 400 whose errors map names "
            "the element's path and capabilities"
        ),
    )
    token = server.token or ""
    disagreements: list[str] = []

    # The token's own shape - the value never prints, only the verdict. Discharges the
    # prior-probe on "AccessToken is 32 lowercase hex" (002 spec section 3.1's table).
    probe.observe(
        "AccessToken shape",
        "32 lowercase hex"
        if re.fullmatch(r"[0-9a-f]{32}", token)
        else f"NOT 32 lowercase hex ({len(token)} chars)",
    )

    # -- the five mechanisms, by route class ---------------------------------------------------

    api_refuses, api_all_five = measure_route_class(
        probe, server, f"API {API_ROUTE}", API_ROUTE, {}, token
    )
    if not api_refuses:
        disagreements.append(f"{API_ROUTE} answered without a token, so it authenticates nothing")
    if not api_all_five:
        disagreements.append("not all five mechanisms authenticated the API route")

    image_id = find_image_item(server)
    if image_id:
        refuses, all_five = measure_route_class(
            probe,
            server,
            "image /Items/{id}/Images/Primary",
            f"/Items/{image_id}/Images/Primary",
            {"maxWidth": "1"},
            token,
        )
        if not all_five:
            disagreements.append("not all five mechanisms authenticated the image route")
        if not refuses:
            probe.note(
                "the image route answered WITHOUT a token. That is a finding about the reference "
                "rather than about the mechanisms - AC-3 asserts that all five work on an image "
                "route, and on a route that authenticates nobody all five trivially do."
            )
    else:
        probe.note(
            "image route NOT measured: the reference has no item carrying a primary image. AC-3 "
            "covers three route classes and this run covers what it could reach."
        )

    video = find_item(server, IncludeItemTypes="Movie,Episode,Video", MediaTypes="Video")
    if video:
        refuses, all_five = measure_route_class(
            probe,
            server,
            "delivery /Videos/{id}/stream",
            f"/Videos/{video['Id']}/stream",
            {"static": "true"},
            token,
        )
        if not all_five:
            disagreements.append("not all five mechanisms authenticated the delivery route")
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

    # -- the header grammar: lenient in six ways, strict in two, and the scheme word required --
    # behaviours section 2.12's table and 002 spec section 3.2's scheme claim, measured as the
    # token grammar on the API route. The header value carries the live token, so only the
    # variation label and the status are ever printed.

    for variation, value, read in grammar_variations(token):
        status, _, _ = request(server, "GET", API_ROUTE, headers={"Authorization": value})
        expected = 200 if read else 401
        marker = "" if (status < 400) == read else f"   <-- expected {expected}"
        probe.observe(f"grammar: {variation}", f"{status}{marker}")
        if (status < 400) != read:
            disagreements.append(
                f"the header grammar row '{variation}' answered {status}, "
                f"where behaviours section 2.12 records {expected}"
            )

    # -- behaviours 2.13: DeviceId is mandatory on one route, not on the header ----------------
    # The 400 half is measured on AuthenticateByName below; this is the 200 half - the same
    # DeviceId-less header on an ordinary authenticated route is served normally.

    status, _, _ = request(
        server,
        "GET",
        API_ROUTE,
        headers={"X-Emby-Token": token, "X-Emby-Authorization": CLIENT_HEADER_WITHOUT_DEVICE_ID},
    )
    probe.observe("header without DeviceId, ordinary route", str(status))
    if status >= 400:
        disagreements.append(
            f"a DeviceId-less client header on an ordinary route answered {status}, not the "
            "measured 200 (behaviours section 2.13)"
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

        # The same components, in the other spelling. Every call this probe had ever made set
        # X-Emby-Authorization, so the route's requirement was measured for one name while
        # api-surface-v1.md section 3 documents both.
        other_spelling = authenticate(
            server, username, password, header=CLIENT_HEADER, header_name="Authorization"
        )
        probe.observe(f"{AUTHENTICATE}: client components in Authorization", shape(*other_spelling))
        if other_spelling[0] >= 400:
            disagreements.append(
                f"a sign-in carrying the client components in Authorization answered "
                f"{other_spelling[0]}, so the route wants the X-Emby-Authorization spelling after "
                "all - api-surface-v1.md section 3 says either works, and a real tvOS client "
                "sends only this one"
            )

        if missing_header != 400:
            disagreements.append(
                f"a sign-in with no client header at all answered {missing_header}, not 400"
            )
        if missing_device != 400:
            disagreements.append(f"a header without DeviceId answered {missing_device}, not 400")
    else:
        probe.note(
            "the two 400 paths on AuthenticateByName, and the sign-in through Authorization, "
            "were NOT measured: sending them needs a password, and this run authenticated with a "
            "token. Re-run with --username to measure them - correct credentials are used, so "
            "nothing counts as a failed attempt."
        )

    # -- what a caller with no token learns ----------------------------------------------------

    measure_public_users(probe, server, disagreements)

    # -- the CamelCase profile reaches inside Policy (compat/model.py's PropertyKeyed) ---------

    status, _, camel = request(
        server,
        "GET",
        API_ROUTE,
        headers={"X-Emby-Token": token, "Accept": 'application/json; profile="CamelCase"'},
        read_limit=1 << 20,
    )
    inside: dict[str, Any] = {}
    if status == 200:
        with contextlib.suppress(ValueError):
            inside = json.loads(camel).get("policy") or {}
    probe.observe(
        "CamelCase profile",
        f"{status}; policy.isAdministrator "
        + ("present" if "isAdministrator" in inside else "ABSENT"),
    )
    if "isAdministrator" not in inside:
        disagreements.append(
            "under the CamelCase profile the key conversion did not reach inside Policy - "
            "policy.isAdministrator was absent (compat/model.py's claim)"
        )

    # -- the sign-in body's shapes, and the probe's own session's capabilities -----------------

    if server.username_used and server.password_used is not None:
        fresh = authenticate(
            server, server.username_used, server.password_used, header=CLIENT_HEADER
        )
        if fresh[0] != 200:
            probe.note(
                f"a fresh sign-in for the body measurements answered {fresh[0]}, so the "
                "sign-in-body and capabilities claims were not measured"
            )
        else:
            body = json.loads(fresh[2])
            measure_signin_body(probe, disagreements, body)
            measure_capabilities(probe, server, disagreements, str(body.get("AccessToken") or ""))
    else:
        probe.note(
            "the sign-in-body and capabilities claims were NOT measured: they need a fresh "
            "session of this probe's own, and this run authenticated with a token. Re-run with "
            "--username."
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

        if disabled_status != 403:
            disagreements.append(
                f"a disabled user answered {disabled_status}, not the measured 403 (OQ-3, "
                "behaviours section 2.11)"
            )
        if right[2] != unknown[2]:
            disagreements.append(
                "the disabled-account body differs from the unknown-username body - the status "
                "is supposed to be the whole of the difference"
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
            "every mechanism measured authenticated every route class measured; the grammar, "
            "DeviceId, sign-in-body, /Users/Public and capabilities claims all held as "
            "documented; and a disabled account is refused with 403 whether the password is "
            "right or wrong, its body identical to the unknown-username 401's",
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
