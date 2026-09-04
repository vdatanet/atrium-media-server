#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Does the reference refuse `GET /System/Info` to a valid token without the relevant permission?

[001 section 3.2](../specs/001-server-identity-and-discovery/spec.md)'s error table carries the
row `| Valid token without permission | 403 |` **with no citation**, and Atrium's route gates on
nothing but "there is a user". The 2026-09-04 audit's H1 says which of the two is wrong cannot be
settled by reading, so this is the reading it asked for.

**Which permission, though.** The reference's route declares
`Policy = FirstTimeSetupOrIgnoreParentalControl`
`[source: Jellyfin.Api/Controllers/SystemController.cs:67-71 @ v10.11.11]`, which is registered as
`FirstTimeSetupRequirement(validateParentalSchedule: false, requireAdmin: false)`
`[source: Jellyfin.Server/Extensions/ApiServiceCollectionExtensions.cs:78 @ v10.11.11]`. Two
handlers see that requirement:

* `FirstTimeSetupHandler` succeeds while the startup wizard is incomplete, succeeds for the
  `Administrator` role, and - because `requireAdmin` is false - succeeds for the `User` role
  `[source: Jellyfin.Api/Auth/FirstTimeSetupPolicy/FirstTimeSetupHandler.cs:29-52 @ v10.11.11]`.
  Its remaining branch, the one that neither succeeds nor fails, needs the `Guest` role, and
  **no token is ever issued one**: the authentication handler assigns `Administrator` to an API
  key or an administrator and `User` to everybody else, and names `Guest` nowhere
  `[source: Jellyfin.Api/Auth/CustomAuthenticationHandler.cs:53-57 @ v10.11.11]`.
* `DefaultAuthorizationHandler` runs on the same requirement because the requirement subclasses
  its own, and it is the only one of the two that can *fail*. It fails on exactly one condition
  reachable here - **the caller is outside the LAN and the account does not hold
  `EnableRemoteAccess`** - and it tests that condition *before* the administrator bypass
  `[source: Jellyfin.Api/Auth/DefaultAuthorizationPolicy/DefaultAuthorizationHandler.cs:52-88
  @ v10.11.11]`. Parental schedule, the other failure it holds, is switched off by this policy.

So there is exactly one permission that can produce the row's `403`, it is `EnableRemoteAccess`,
and it only bites from an address the server does not count as local. A probe that varies the
permission alone measures `200` every time and files it as "the reference does not refuse"; a
probe that only tries an administrator measures `200` too. This one measures the whole
2x2 - local or remote, permission held or not - and repeats the refusing cell as an
administrator, because a check that runs before the administrator bypass is not a per-route
permission and the difference decides what closing H1 would cost.

**It never touches a server somebody owns.** Making the caller remote means redefining what the
server counts as its LAN, which is a change to who may reach that server at all; on somebody's
installation that is not a measurement anybody may take. So this stands up a single-use instance
of the pinned version, narrows its `LocalNetworkSubnets` so the probe's own address falls outside
it - **verified through `/System/Endpoint`'s own `IsInNetwork`, not assumed** - and destroys the
instance including on failure. Naming a server on the command line is refused rather than
honoured. Two throwaway accounts are created and deleted, which is `tools/probe_user_read.py`'s
precedent for a question of this shape.

Standard library only, on the 3.9 floor, and `--help` starts nothing.

Usage:
    python3 tools/probe_system_info_permission.py --allow-writes
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import json
import secrets
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
REPOSITORY = HERE.parent

#: An empty directory to mount: the question has nothing to do with a library, and scanning one
#: would only be time. `reference/` is git-ignored, and a system temporary directory is not a path
#: a container runtime will mount on macOS - `probe_reference_scan.py`'s finding.
TREE = REPOSITORY / "reference" / "empty-tree"

#: The two throwaway accounts. The second exists only to ask the refusing cell as an
#: administrator, which is how "this is a per-route permission" is told from "this runs before
#: the administrator bypass".
SEAT = "atrium-probe-sysinfo"
ADMIN_SEAT = "atrium-probe-sysinfo-admin"

#: TEST-NET-3 (RFC 5737). Declared as the instance's whole LAN so that the probe's own address -
#: whatever the container runtime gives it - is outside it. Documentation address space is used
#: rather than a plausible private range precisely because nothing can be on it.
ELSEWHERE = "203.0.113.0/24"

#: `EnableAllDevices` is the one permission this probe leaves alone. With it false and
#: `EnabledDevices` empty the account cannot authenticate from any device at all, which would
#: refuse the seat at sign-in and answer a question about devices under the name of this one.
KEEP = ("EnableAllDevices",)

DOCUMENT = "specs/001-server-identity-and-discovery/spec.md"
SECTION = "section 3.2, the error table (2026-09-04 audit H1)"
EXPECTATION = (
    "001 section 3.2: GET /System/Info answers 403 to a valid token without permission - a row "
    "carrying no citation, which AC-5 ('200 with a valid one') reads as the opposite of"
)


def load(name: str) -> Any:
    """A sibling of this script, loaded by path and on first use, never at import.

    `tools/` is a directory of standalone programs and not an importable package, which is how
    every other tool here reaches its siblings.
    """
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, HERE / (name + ".py"))
    if spec is None or spec.loader is None:  # pragma: no cover - the files are beside this one
        raise SystemExit(f"tools/{name}.py could not be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def policy_of(server: Any, user_id: str) -> Dict[str, Any]:
    return dict((server.get(f"/Users/{user_id}") or {}).get("Policy") or {})


def write_policy(server: Any, user_id: str, changes: Dict[str, Any]) -> Dict[str, Any]:
    """Apply `changes` to the account's whole policy and read back what the server stored.

    The **whole policy** and not a one-key body: `POST /Users/{userId}/Policy` binds a complete
    `UserPolicy` `[spec: UpdateUserPolicy, UserPolicy]`, so a body carrying one property would
    reset every other permission to its default and measure a different account than the one that
    was read. Read back, because a flag this probe set and never checked is a flag it is
    asserting rather than measuring.
    """
    policy = policy_of(server, user_id)
    policy.update(changes)
    server.post(f"/Users/{user_id}/Policy", body=policy)
    return policy_of(server, user_id)


def strip_permissions(policy: Dict[str, Any]) -> Dict[str, bool]:
    """Every `Enable*` boolean the server reported, set false - `KEEP` excepted.

    Derived from what the server answered rather than from a list written here, so an account
    this probe calls "holding no permission" holds none of the ones *that* version has.
    """
    return {
        name: False
        for name, value in policy.items()
        if name.startswith("Enable") and isinstance(value, bool) and name not in KEEP
    }


def endpoint(server: Any) -> Tuple[int, Any, Any]:
    """`/System/Endpoint`, the reference's own answer to "do you count me as local?".

    It reports `IsInNetwork = IsInLocalNetwork(remote address)` - the identical call the
    authorization handler makes `[source: Jellyfin.Api/Controllers/SystemController.cs:186-196
    @ v10.11.11]`. Reading it is what turns "the LAN was narrowed" from an assumption into a
    measurement.
    """
    status, _headers, payload = server.get_raw("/System/Endpoint")
    if status != 200:
        return status, None, None
    body = json.loads(payload)
    return status, body.get("IsLocal"), body.get("IsInNetwork")


def answer(server: Any, path: str, send_token: bool = True) -> Tuple[int, str]:
    """One request, reported as the status and the bytes a client would have to read."""
    status, headers, payload = server.get_streaming(path, 200, send_token=send_token)
    return status, f"{status} {headers.get('Content-Type')} {payload[:80]!r}"


class Reading:
    """The instance, and the readings taken on it."""

    def __init__(self) -> None:
        self.instance: Optional[Any] = None

    @contextlib.contextmanager
    def connect(self, args: argparse.Namespace) -> Iterator[Any]:
        probe = load("_probe")
        reference = load("_reference")
        if getattr(args, "server", None):
            raise probe.ProbeError(
                "this probe refuses a server argument. Answering its question means redefining "
                "what the server counts as its local network, which changes who may reach that "
                "server at all - so it measures only an instance it creates and destroys itself "
                "(010 spec section 3.1), never a server somebody owns"
            )
        TREE.mkdir(parents=True, exist_ok=True)
        try:
            spec = reference.InstanceSpec(fixture_root=TREE, libraries=())
            with reference.ReferenceInstance(spec) as instance:
                self.instance = instance
                administrator = instance.administrator
                server = probe.Server(instance.url)
                server.connect(administrator.username, administrator.password, None)
                yield server
        except reference.InstanceError as failure:
            raise probe.ProbeError(str(failure)) from failure
        finally:
            shutil.rmtree(TREE, ignore_errors=True)

    def report(self, server: Any, _args: argparse.Namespace) -> Any:
        module = load("_probe")
        probe = module.Probe(
            script="probe_system_info_permission.py",
            question="does the reference refuse GET /System/Info to a valid token without the "
            "permission its policy reads?",
            document=DOCUMENT,
            section=SECTION,
            expectation=EXPECTATION,
        )
        probe.observe("instance", self.instance.image if self.instance else "unknown")

        checks: List[bool] = []
        password = secrets.token_hex(12)
        admin_password = secrets.token_hex(12)
        seat_id = str(server.post("/Users/New", body={"Name": SEAT, "Password": password})["Id"])
        admin_id = str(
            server.post("/Users/New", body={"Name": ADMIN_SEAT, "Password": admin_password})["Id"]
        )

        seat = module.Server(server.base, timeout=server.timeout)
        seat.connect(SEAT, password, None)
        elevated = module.Server(server.base, timeout=server.timeout)
        elevated.connect(ADMIN_SEAT, admin_password, None)

        # -- the seat -------------------------------------------------------------------------
        stored = write_policy(server, seat_id, strip_permissions(policy_of(server, seat_id)))
        held = sorted(name for name, value in stored.items() if name.startswith("Enable") and value)
        probe.observe("the seat, IsAdministrator", stored.get("IsAdministrator"))
        probe.observe("the seat, permissions it still holds", held or "none")
        checks.append(stored.get("IsAdministrator") is False and held == ["EnableAllDevices"])

        raised = write_policy(server, admin_id, {"IsAdministrator": True})
        probe.observe("the second seat, IsAdministrator", raised.get("IsAdministrator"))
        checks.append(raised.get("IsAdministrator") is True)

        # -- on the LAN, which is where the instance starts ------------------------------------
        status, is_local, in_network = endpoint(server)
        probe.observe(
            "/System/Endpoint as created",
            f"{status} IsLocal={is_local} IsInNetwork={in_network}",
        )
        checks.append(status == 200 and in_network is True)

        _, local_no_permission = answer(seat, "/System/Info")
        probe.observe("local, an account holding no permission", local_no_permission)
        checks.append(local_no_permission.startswith("200 "))

        write_policy(server, seat_id, {"EnableRemoteAccess": False})
        _, local_no_remote = answer(seat, "/System/Info")
        probe.observe("local, EnableRemoteAccess also false", local_no_remote)
        checks.append(local_no_remote.startswith("200 "))

        # -- the same account, from an address the server does not count as its own ------------
        network = dict(server.get("/System/Configuration/network") or {})
        was = list(network.get("LocalNetworkSubnets") or [])
        probe.observe("LocalNetworkSubnets as created", was or "[] - every private range is LAN")
        try:
            network["LocalNetworkSubnets"] = [ELSEWHERE]
            server.post("/System/Configuration/network", body=network)
            status, is_local, in_network = endpoint(server)
            probe.observe(
                "/System/Endpoint with the LAN narrowed",
                f"{status} IsLocal={is_local} IsInNetwork={in_network}",
            )
            if not (status == 200 and in_network is False):
                probe.conclude(
                    "the caller could not be made remote: with LocalNetworkSubnets narrowed to "
                    f"{ELSEWHERE} the reference still answers IsInNetwork={in_network}, so the "
                    "one condition that can refuse this route was never reached and nothing "
                    "here is a measurement of it",
                    matches_documentation=None,
                )
                return probe
            checks.append(True)

            _, remote_no_remote = answer(seat, "/System/Info")
            probe.observe("remote, EnableRemoteAccess false", remote_no_remote)
            checks.append(remote_no_remote.startswith("403 "))

            _, remote_me = answer(seat, "/Users/Me")
            probe.observe("remote, EnableRemoteAccess false, /Users/Me", remote_me)
            checks.append(remote_me.startswith("403 "))

            _, remote_public = answer(seat, "/System/Info/Public", send_token=False)
            probe.observe("remote, no token at all, /System/Info/Public", remote_public)
            checks.append(remote_public.startswith("200 "))

            _, remote_anonymous = answer(seat, "/System/Info", send_token=False)
            probe.observe("remote, no token at all, /System/Info", remote_anonymous)
            checks.append(remote_anonymous.startswith("401 "))

            write_policy(server, seat_id, {"EnableRemoteAccess": True})
            _, remote_with_remote = answer(seat, "/System/Info")
            probe.observe("remote, EnableRemoteAccess true, nothing else", remote_with_remote)
            checks.append(remote_with_remote.startswith("200 "))

            write_policy(server, admin_id, {"EnableRemoteAccess": False})
            _, remote_administrator = answer(elevated, "/System/Info")
            probe.observe(
                "remote, an administrator with EnableRemoteAccess false", remote_administrator
            )
            checks.append(remote_administrator.startswith("403 "))
            write_policy(server, admin_id, {"EnableRemoteAccess": True})
        finally:
            network["LocalNetworkSubnets"] = was
            server.post("/System/Configuration/network", body=network)
            status, _is_local, in_network = endpoint(server)
            probe.observe("LocalNetworkSubnets restored", f"{status} IsInNetwork={in_network}")

        for name, identifier in ((SEAT, seat_id), (ADMIN_SEAT, admin_id)):
            status, _headers, _payload = server.delete_raw(f"/Users/{identifier}")
            probe.observe(f"{name} deleted", status)

        probe.note(
            "The row is right that a `403` exists and wrong about what reaches it. There is no "
            "permission on this route: the policy's own handler succeeds for every role the "
            "reference issues, and the `Guest` branch that would refuse is unreachable because "
            "no token is ever given that role "
            "`[source: Jellyfin.Api/Auth/CustomAuthenticationHandler.cs:53-57 @ v10.11.11]`. The "
            "refusal comes from the default handler underneath it, on `EnableRemoteAccess`, and "
            "only from an address outside the LAN."
        )
        probe.note(
            "It is not this route's refusal. The same seat is refused `/Users/Me` in the same "
            "breath, and an **administrator** is refused too - the remote-access test runs "
            "before the administrator bypass "
            "`[source: Jellyfin.Api/Auth/DefaultAuthorizationPolicy/DefaultAuthorizationHandler."
            "cs:52-88 @ v10.11.11]`. Anything built from this measurement is a server-wide gate "
            "on every authorized route, not a check inside `get_system_info`."
        )
        probe.note(
            "Being remote is measured and not assumed. `/System/Endpoint` reports the identical "
            "`IsInLocalNetwork(remote address)` call the handler makes, and it reads true before "
            "the LAN is narrowed and false after - so the refusing cell is known to differ from "
            "the passing one in the condition this probe meant to change."
        )

        refuses = all(checks)
        probe.conclude(
            (
                "**it refuses, on one permission and only from outside the LAN.** An account "
                "holding no permission at all answers `200` while the caller is local, with "
                "`EnableRemoteAccess` set either way. Redefine the LAN so the same caller is "
                "remote - `/System/Endpoint` flips `IsInNetwork` to false - and the account "
                "without `EnableRemoteAccess` is refused `403`, while the same account with it "
                "answers `200`. The refusal is not the route's: `/Users/Me` is refused "
                "identically, and so is an **administrator** who lacks the flag"
                if refuses
                else "the cells did not come out as the source reads: "
                + ", ".join(f"check {i}" for i, ok in enumerate(checks) if not ok)
                + " - see the observations"
            ),
            matches_documentation=refuses,
        )
        return probe


def main() -> int:
    reading = Reading()
    return int(
        load("_probe").main(
            reading.report,
            description=(
                "Measure whether the reference refuses GET /System/Info to a valid token "
                "without the permission its policy reads (2026-09-04 audit, H1). Stands up a "
                "single-use instance of the pinned version, builds a seat that holds no "
                "permission, varies the one flag the route's policy can fail on and whether the "
                "caller is on the LAN, and destroys the instance - including on failure. It "
                "never measures a server somebody owns."
            ),
            needs_writes=True,
            with_args=True,
            connect_with=reading.connect,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
