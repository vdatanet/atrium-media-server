#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""What do `GET /Sessions`' three query parameters narrow, and does the narrowing run before or
after the rule about whose sessions a caller may see?

The route belongs to [002 section 3.8](../specs/002-authentication-users-and-sessions/spec.md),
which specifies the visibility rule and declares none of the parameters. The reference declares
three - `controllableByUserId`, `deviceId` and `activeWithinSeconds`
`[source: Jellyfin.Api/Controllers/SessionController.cs:52-59 @ v10.11.11]` - and the interesting
half of the question is not the convenience: it is what a non-administrator gets back when the
parameter names somebody else's device or somebody else's user. That is a sentence about who may
see whose device, and it is 002's sentence.

Measured at 012's gate because a measurement session is cheap to extend and expensive to convene
(012 section 2.1, OQ-7); **specified in 002**, in the change that adds the parameters. Nothing in
012 depends on the answer.

The probe needs a second session that is not the caller's own, and a non-administrator to ask the
visibility questions as. Both are the same throwaway account: it is created, authenticated with a
device id of its own, declares itself remote-controllable, and is deleted again - including on
failure. An administrator token is required to create it.

Usage:
    python3 tools/probe_session_filters.py http://your-jellyfin:8096 -u admin --allow-writes
"""

from __future__ import annotations

import base64
import json
import secrets
import socket
import ssl
import time
import urllib.parse
from typing import Any

from _probe import Probe, ProbeError, Server, main

#: The throwaway account. Its device has to differ from the administrator's or the two sessions
#: are one session and every filter measures nothing - which `_probe.Server` now guarantees by
#: deriving a device from the account (010 T13), where this probe used to swap a module constant
#: around the sign-in and was the only one that did.
THROWAWAY_USER = "atrium-probe-sessions"

#: A well-formed identifier no user owns - the same constant probe_playback_info.py uses, and for
#: the same reason: a malformed one measures the model binder rather than the lookup.
NOBODY = "a7c1f5e30b9d4a6c8e2f1b3d5a7c9e10"


def open_control_channel(server: Server, device_id: str) -> socket.socket | None:
    """Open the session's control channel, because `controllableByUserId` filters on having one.

    A session is remote-controllable only while something is attached to it that can carry a
    command `[source: MediaBrowser.Controller/Session/SessionInfo.cs:246-266 @ v10.11.11]`, and
    nothing a request-response client does creates one. So a probe that only makes requests
    measures an empty answer and attributes it to the parameter.

    Forty lines of RFC 6455 handshake rather than a dependency, in keeping with the rest of
    tools/. Nothing is read or written after the upgrade: the socket exists to be open. Returns
    None when the upgrade is refused, which is a reason to note rather than to fail.
    """
    parts = urllib.parse.urlsplit(server.base)
    port = parts.port or (443 if parts.scheme == "https" else 80)
    query = urllib.parse.urlencode({"api_key": server.token or "", "deviceId": device_id})
    key = base64.b64encode(secrets.token_bytes(16)).decode()
    request = (
        f"GET /socket?{query} HTTP/1.1\r\n"
        f"Host: {parts.hostname}:{port}\r\n"
        "Upgrade: websocket\r\nConnection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
    )
    try:
        raw = socket.create_connection((parts.hostname, port), timeout=15)
        if parts.scheme == "https":
            raw = ssl.create_default_context().wrap_socket(raw, server_hostname=parts.hostname)
        raw.sendall(request.encode())
        raw.settimeout(15)
        head = raw.recv(4096)
    except OSError:
        return None
    if not head.startswith(b"HTTP/1.1 101"):
        raw.close()
        return None
    #: The listener attaches the controller when it accepts the socket, not when the socket is
    #: created, so the next request has to happen after it - not at the same time as it.
    time.sleep(1.5)
    return raw


def _sessions(server: Server, **query: Any) -> tuple[int, list[tuple[str, str]] | bytes]:
    status, headers, payload = server.get_raw("/Sessions", **query)
    if status != 200:
        return status, f"{headers.get('Content-Type')} {payload[:60]!r}".encode()
    rows = json.loads(payload)
    return status, sorted({(r.get("DeviceId") or "", r.get("UserName") or "") for r in rows})


def _count(answer: tuple[int, Any]) -> str:
    status, rows = answer
    if status != 200:
        return f"{status} {rows.decode() if isinstance(rows, bytes) else rows}"
    return f"{status}, {len(rows)} session(s)"


def _device_battery(server: Server, probe: Probe, own: str, theirs: str) -> list[bool]:
    checks: list[bool] = []
    everything = _sessions(server)
    probe.observe("no parameter at all", _count(everything))
    total = len(everything[1])

    exact = _sessions(server, deviceId=own)
    probe.observe("deviceId, the caller's own", f"{_count(exact)} {exact[1]}")
    checks.append(exact[0] == 200 and len(exact[1]) == 1 and exact[1][0][0] == own)

    other = _sessions(server, deviceId=theirs)
    probe.observe("deviceId, another user's device", f"{_count(other)} {other[1]}")
    checks.append(other[0] == 200 and len(other[1]) == 1 and other[1][0][0] == theirs)

    upper = _sessions(server, deviceId=own.upper())
    probe.observe("deviceId, the same id upper-cased", _count(upper))
    checks.append(upper[0] == 200 and upper[1] == exact[1])

    unknown = _sessions(server, deviceId="atrium-probe-no-such-device")
    probe.observe("deviceId, no session has it", _count(unknown))
    checks.append(unknown[0] == 200 and not unknown[1])

    empty = _sessions(server, deviceId="")
    probe.observe("deviceId, empty string", _count(empty))
    checks.append(empty[0] == 200 and len(empty[1]) == total)
    return checks


def _active_battery(server: Server, probe: Probe) -> list[bool]:
    checks: list[bool] = []
    total = len(_sessions(server)[1])
    narrow = _sessions(server, activeWithinSeconds=1)
    wide = _sessions(server, activeWithinSeconds=99_999)
    probe.observe("activeWithinSeconds=1", _count(narrow))
    probe.observe("activeWithinSeconds=99999", _count(wide))
    checks.append(len(narrow[1]) <= len(wide[1]) <= total)

    for value in (0, -5):
        answer = _sessions(server, activeWithinSeconds=value)
        probe.observe(f"activeWithinSeconds={value}", _count(answer))
        checks.append(answer[0] == 200 and len(answer[1]) == total)
    return checks


def _controllable_battery(
    server: Server, probe: Probe, other_user_id: str, own: str, theirs: str
) -> list[bool]:
    checks: list[bool] = []
    mine = _sessions(server, controllableByUserId=server.user_id)
    probe.observe("controllableByUserId, the caller", f"{_count(mine)} {mine[1]}")
    checks.append(mine[0] == 200)

    theirs_answer = _sessions(server, controllableByUserId=other_user_id)
    probe.observe(
        "controllableByUserId, the other user", f"{_count(theirs_answer)} {theirs_answer[1]}"
    )
    checks.append(theirs_answer[0] == 200 and any(row[0] == theirs for row in theirs_answer[1]))

    probe.note(
        "Every session on this server other than the throwaway one answers "
        "`controllableByUserId` with nothing, and the reason is not the parameter: a session is "
        "remote-controllable only while a control channel is attached to it "
        "`[source: MediaBrowser.Controller/Session/SessionInfo.cs:246-266 @ v10.11.11]`, which a "
        "request-response client never has. Declaring `SupportsMediaControl` is necessary and "
        "not sufficient."
    )

    nobody = _sessions(server, controllableByUserId=NOBODY)
    probe.observe("controllableByUserId, a user nothing owns", _count(nobody))
    checks.append(nobody[0] == 200 and not nobody[1])

    both = _sessions(server, controllableByUserId=other_user_id, deviceId=own)
    probe.observe("controllableByUserId with a deviceId that is not theirs", _count(both))
    checks.append(both[0] == 200)
    return checks


def _visibility_battery(
    admin: Server, other: Server, probe: Probe, admin_device: str, their_device: str
) -> list[bool]:
    """The half that is not a convenience: who may see whose device, asked as the other user."""
    checks: list[bool] = []
    bare = _sessions(other)
    probe.observe("as a non-administrator, no parameter", f"{_count(bare)} {bare[1]}")
    checks.append(bare[0] == 200 and len(bare[1]) == 1 and bare[1][0][0] == their_device)

    someone_elses = _sessions(other, deviceId=admin_device)
    probe.observe("as a non-administrator, another user's deviceId", _count(someone_elses))
    checks.append(someone_elses[0] == 200 and not someone_elses[1])

    own = _sessions(other, deviceId=their_device)
    probe.observe("as a non-administrator, their own deviceId", _count(own))
    checks.append(own[0] == 200 and len(own[1]) == 1)

    self_control = _sessions(other, controllableByUserId=other.user_id)
    probe.observe("as a non-administrator, controllableByUserId=self", _count(self_control))
    checks.append(self_control[0] == 200)

    status, headers, payload = other.get_raw("/Sessions", controllableByUserId=admin.user_id)
    probe.observe(
        "as a non-administrator, controllableByUserId=somebody else",
        f"{status} {headers.get('Content-Type')} {payload[:60]!r}",
    )
    checks.append(status == 403)
    return checks


def run(server: Server, args) -> Probe:
    probe = Probe(
        script="probe_session_filters.py",
        question="what do the session list's three parameters narrow, and does the narrowing run "
        "before or after the rule about whose sessions a caller may see?",
        document="specs/002-authentication-users-and-sessions/spec.md",
        section="section 3.8 (measured at 012's gate, OQ-7)",
    )
    me = server.get("/Users/Me")
    if not me["Policy"]["IsAdministrator"]:
        raise ProbeError(
            "this probe needs an administrator: the second session it compares against belongs "
            "to a throwaway user only an administrator can create"
        )

    password = secrets.token_hex(12)
    made = server.post("/Users/New", body={"Name": THROWAWAY_USER, "Password": password})
    user_id = made["Id"]
    try:
        other = Server(server.base, timeout=server.timeout)
        other.connect(THROWAWAY_USER, password, None)

        #: Without this the throwaway session is not remote-controllable, and every
        #: controllableByUserId answer is empty for a reason that has nothing to do with the
        #: parameter.
        status, _, _payload = other.post_raw(
            "/Sessions/Capabilities/Full",
            body={
                "PlayableMediaTypes": ["Video", "Audio"],
                "SupportedCommands": ["Play"],
                "SupportsMediaControl": True,
                "SupportsPersistentIdentifier": False,
            },
        )
        if status != 204:
            raise ProbeError(f"could not make the throwaway session controllable: {status}")

        channel = open_control_channel(other, other.device_id)
        probe.observe(
            "control channel for the throwaway session",
            "open" if channel else "refused - controllableByUserId cannot be measured",
        )

        checks = _device_battery(server, probe, server.device_id, other.device_id)
        checks += _active_battery(server, probe)
        checks += _controllable_battery(server, probe, user_id, server.device_id, other.device_id)
        checks += _visibility_battery(server, other, probe, server.device_id, other.device_id)
        if channel is not None:
            channel.close()
    finally:
        status, _, _ = server.delete_raw(f"/Users/{user_id}")
        probe.observe("throwaway user deleted", status)

    probe.note(
        "The order is readable in the answers and it is not the obvious one: `deviceId` is "
        "applied to the whole session list first, and the visibility rule then removes what the "
        "caller may not see - so a non-administrator naming another user's device gets an empty "
        "200 rather than a refusal, and only `controllableByUserId` naming another user is "
        "refused outright. `activeWithinSeconds` is applied last, and a value of zero or less is "
        "ignored rather than refused, which is behaviours section 1.12's family."
    )
    probe.note(
        "Owed to 002, not to 012: nothing in specs/012-negotiation-inputs/spec.md depends on any "
        "of this. The row it belongs in is 002 section 3.8's, in the change that adds the three "
        "parameters."
    )

    if all(checks):
        probe.conclude(
            "all three narrow, and they are three different kinds of narrowing. `deviceId` "
            "matches case-insensitively, runs before the visibility rule and is ignored when "
            "empty. `activeWithinSeconds` runs last and is ignored at zero and below. "
            "`controllableByUserId` is not a filter at all but a different visibility rule: it "
            "keeps only sessions that declared themselves remote-controllable, answers empty for "
            "a user id nothing owns, and - the half that is 002's own sentence - answers 403 "
            "when a non-administrator names anybody but themselves, where naming another user's "
            "*device* answers an empty 200",
            matches_documentation=None,
        )
    else:
        failed = [i for i, ok in enumerate(checks) if not ok]
        probe.conclude(f"checks {failed} did not hold - see observations", False)
    return probe


if __name__ == "__main__":
    raise SystemExit(main(run, __doc__.splitlines()[0], needs_writes=True, with_args=True))
