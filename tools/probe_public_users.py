#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Does `/Users/Public` answer an empty list when every account is hidden from the login screen?

That is one of the two prior measurements
[reference-target.md](../docs/compatibility/reference-target.md) has carried open since
2026-06-13, and **not for want of an author**: the route is read on every run of
`tools/probe_auth_mechanisms.py` and every run answers complete user objects, because the `[]`
needs an installation where *every* user is hidden. Hiding an operator's users is a write to their
own accounts and a change to what their login screen shows, which is not a measurement anybody may
take on somebody else's server. It became askable the day 010 T9 landed a Jellyfin this project
stands up and destroys, and the register names this task - 010 T13 - as the one that pays it.

**It never touches a server somebody owns.** It stands up a single-use instance of the pinned
version, hides the accounts on it, reads the route, and destroys the instance including on
failure. Naming a server on the command line is refused rather than honoured.

Standard library only, on the 3.9 floor, and `--help` starts nothing.

Usage:
    python3 tools/probe_public_users.py --allow-writes
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

HERE = Path(__file__).resolve().parent
REPOSITORY = HERE.parent

#: An empty directory to mount, because the question has nothing to do with a library and a scan
#: of one would only be time. `reference/` is already git-ignored, and a system temporary directory
#: is not a path a container runtime will mount on macOS - which is `probe_reference_scan.py`'s
#: finding and the reason this is not `tempfile`.
TREE = REPOSITORY / "reference" / "empty-tree"

#: The throwaway account this probe adds so that the answer is about **every** user rather than
#: about the only one. Removed with the instance either way.
SECOND_ACCOUNT = "atrium-probe-public"

DOCUMENT = "docs/compatibility/behaviours.md"
SECTION = "section 2.2"
EXPECTATION = (
    "behaviours section 2.2: the reference honours each user's hidden-from-login-screens policy "
    "flag and returns 200 with [] when every user is hidden"
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


def public_users(anonymous: Any) -> List[Dict[str, Any]]:
    """The route as a login screen asks it: **no credential at all**.

    Which matters, because two of the four filters behind this route read the caller. It answers
    `Get(isHidden: false, isDisabled: false, filterByDevice: true, filterByNetwork: true)`
    `[source: Jellyfin.Api/Controllers/UserController.cs:109-117 @ v10.11.11]`, and the device
    filter reads the **token's** device while the network filter reads the remote address
    `[source: Jellyfin.Api/Controllers/UserController.cs:635-651 @ v10.11.11]`. A probe that sent
    its administrator's token would be measuring which accounts may use the probe's device, and
    would file the answer under the hidden flag.
    """
    rows = anonymous.get("/Users/Public")
    return list(rows) if isinstance(rows, list) else []


def names(rows: List[Dict[str, Any]]) -> str:
    return f"{len(rows)} row(s): {sorted(str(row.get('Name')) for row in rows)}"


def set_hidden(server: Any, user_id: str, hidden: bool) -> bool:
    """Set one account's `IsHidden` and read back what the server stored.

    The **whole policy** and not a one-key body: `POST /Users/{userId}/Policy` binds a complete
    `UserPolicy` `[spec: UpdateUserPolicy, UserPolicy]`, so a body carrying one property would
    reset every other permission to its default and measure a different account than the one that
    was read. Read back, because a flag this probe set and never checked is a flag this probe is
    asserting rather than measuring.
    """
    policy = dict((server.get(f"/Users/{user_id}") or {}).get("Policy") or {})
    policy["IsHidden"] = hidden
    server.post(f"/Users/{user_id}/Policy", body=policy)
    stored = (server.get(f"/Users/{user_id}") or {}).get("Policy") or {}
    return bool(stored.get("IsHidden"))


class Reading:
    """The instance, and the four readings taken on it."""

    def __init__(self) -> None:
        self.instance: Optional[Any] = None

    @contextlib.contextmanager
    def connect(self, args: argparse.Namespace) -> Iterator[Any]:
        probe = load("_probe")
        reference = load("_reference")
        if getattr(args, "server", None):
            raise probe.ProbeError(
                "this probe refuses a server argument. Answering its question means hiding every "
                "account on the server being asked, which changes what its login screen shows - "
                "so it measures only an instance it creates and destroys itself (010 spec "
                "section 3.1), never a server somebody owns"
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
            script="probe_public_users.py",
            question="does /Users/Public answer an empty list when every account is hidden?",
            document=DOCUMENT,
            section=SECTION,
            expectation=EXPECTATION,
        )
        probe.observe("instance", self.instance.image if self.instance else "unknown")

        # A second client with no credential, because that is who calls this route: a login
        # screen has nobody to authenticate as yet.
        anonymous = module.Server(server.base, timeout=server.timeout)

        administrator = server.user_id
        fresh = public_users(anonymous)
        was_hidden = bool(
            ((server.get(f"/Users/{administrator}") or {}).get("Policy") or {}).get("IsHidden")
        )
        probe.observe("the wizard's administrator, IsHidden as created", was_hidden)
        probe.observe("/Users/Public on a server nobody has configured", names(fresh))

        # Visible, so that the flag is measured in both directions rather than assumed in one.
        set_hidden(server, administrator, False)
        one_visible = public_users(anonymous)
        probe.observe("the administrator un-hidden", names(one_visible))

        made = server.post(
            "/Users/New", body={"Name": SECOND_ACCOUNT, "Password": module.device_for("public")}
        )
        second = str(made["Id"])
        created_hidden = bool(
            ((server.get(f"/Users/{second}") or {}).get("Policy") or {}).get("IsHidden")
        )
        probe.observe("a second account, IsHidden as created", created_hidden)
        probe.observe(
            "/Users/Public with the second account created", names(public_users(anonymous))
        )

        set_hidden(server, second, False)
        both = public_users(anonymous)
        probe.observe("both accounts un-hidden", names(both))

        stored = set_hidden(server, second, True)
        one_hidden = public_users(anonymous)
        probe.observe(
            "one of the two hidden, read back as IsHidden=" + str(stored), names(one_hidden)
        )

        # The reading the register has been waiting for since 2026-06-13.
        set_hidden(server, administrator, True)
        status, headers, payload = anonymous.get_raw("/Users/Public")
        empty = public_users(anonymous)
        probe.observe("every account hidden", f"{status} {headers.get('Content-Type')} {payload!r}")

        honours_the_flag = len(both) == 2 and len(one_hidden) == 1 and status == 200 and empty == []
        hidden_by_default = was_hidden and created_hidden and fresh == []
        probe.conclude(
            (
                "the route honours the flag in both directions - two visible accounts, one "
                "hidden narrows it to one, and hiding the last answers 200 with `[]` - and "
                + (
                    "**a fresh installation is already in that state**: IsHidden is true on the "
                    "account the wizard makes and on every account POST /Users/New creates, so "
                    "the empty answer is the default rather than a hardened configuration"
                    if hidden_by_default
                    else "a fresh installation starts with visible accounts"
                )
                if honours_the_flag
                else f"the flag does not drive the route as documented: two un-hidden accounts "
                f"answered {len(both)} row(s), hiding one left {len(one_hidden)}, and hiding "
                f"every account answered {status} with {len(empty)} row(s)"
            ),
            matches_documentation=honours_the_flag,
        )
        probe.note(
            "The route is read with no credential, which is who calls it. Two of its four filters "
            "read the caller - the device comes from the token and the network from the remote "
            "address `[source: Jellyfin.Api/Controllers/UserController.cs:635-651 @ v10.11.11]` - "
            "so an administrator's token turns this into a question about that administrator's "
            "device. The first draft of this probe sent one and measured `[]` at every step."
        )
        probe.note(
            "A client cannot treat an empty list as 'this server has no users' (behaviours "
            "section 2.2). That was already the guidance; what is new is how ordinary the state "
            "is - it is what a server answers before anybody has touched a policy."
        )
        probe.note(
            "The reading needed an instance rather than an author. Hiding every account changes "
            "what an operator's login screen shows, which is why the register carried this row "
            "from 2026-06-13 to 2026-09-02 saying so in its own cell."
        )
        return probe


def main() -> int:
    reading = Reading()
    return int(
        load("_probe").main(
            reading.report,
            description=(
                "Measure what /Users/Public answers when every account is hidden from the login "
                "screen (010 T13, AC-9). Stands up a single-use instance of the pinned version, "
                "hides its accounts, reads the route and destroys the instance - including on "
                "failure. It never measures a server somebody owns."
            ),
            needs_writes=True,
            with_args=True,
            connect_with=reading.connect,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
