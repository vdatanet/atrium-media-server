#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""What exactly does `GET /System/Info/Public` return, before any token exists?

Discharges the prior-probe on the payload recorded in
docs/compatibility/reference-target.md §6 and specs/001 §3.1: the seven fields, their order, and
their shapes were carried forward from a pre-repository measurement (2026-06-13) that nothing
here could re-run. This is the re-run.

Read-only and unauthenticated: the point of the route is that it answers with no token, so the
probe sends none.

Usage:
    python3 tools/probe_public_info.py http://your-jellyfin:8096
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

from _probe import Probe, ProbeError, Server, main

#: specs/001 §3.1's payload: the seven fields, in the order the reference sends them.
EXPECTED_ORDER = [
    "LocalAddress",
    "ServerName",
    "Version",
    "ProductName",
    "OperatingSystem",
    "Id",
    "StartupWizardCompleted",
]

GUID = re.compile(r"^[0-9a-f]{32}$")


def run(server: Server) -> Probe:
    probe = Probe(
        script="probe_public_info.py",
        question="what exactly does /System/Info/Public return, before any token exists?",
        document="specs/001-server-identity-and-discovery/spec.md",
        section="section 3.1",
        expectation=(
            "200 with exactly LocalAddress, ServerName, Version, ProductName, OperatingSystem, "
            "Id, StartupWizardCompleted in that order; ProductName is 'Jellyfin Server', "
            "OperatingSystem is '', Id is 32 lowercase hex"
        ),
    )

    # Deliberately not server.get: that would attach a token when one is configured, and the
    # claim under measurement is what a caller with nothing receives.
    request = urllib.request.Request(  # noqa: S310 - the operator's own server
        server.base + "/System/Info/Public", headers={"Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=server.timeout) as response:  # noqa: S310
            status = response.status
            body = json.loads(response.read())
    except urllib.error.URLError as exc:
        raise ProbeError(f"GET /System/Info/Public -> {exc}") from exc

    keys = list(body)
    probe.observe("status", str(status))
    probe.observe("keys, in wire order", ", ".join(keys))
    probe.observe("ProductName", repr(body.get("ProductName")))
    probe.observe("OperatingSystem", repr(body.get("OperatingSystem")))
    probe.observe("Version", repr(body.get("Version")))
    probe.observe("Id is 32 lowercase hex", str(bool(GUID.match(body.get("Id", "")))))
    probe.observe("StartupWizardCompleted", repr(body.get("StartupWizardCompleted")))
    local_address = str(body.get("LocalAddress", ""))
    probe.observe(
        "LocalAddress shape", "URL" if local_address.startswith("http") else repr(local_address)
    )

    problems: list[str] = []
    if status != 200:
        problems.append(f"status {status}")
    if keys != EXPECTED_ORDER:
        problems.append(f"keys are {keys}")
    if body.get("ProductName") != "Jellyfin Server":
        problems.append(f"ProductName {body.get('ProductName')!r}")
    if body.get("OperatingSystem") != "":
        problems.append(f"OperatingSystem {body.get('OperatingSystem')!r}")
    if not GUID.match(body.get("Id", "")):
        problems.append("Id is not 32 lowercase hex")

    if problems:
        probe.conclude("; ".join(problems), matches_documentation=False)
    else:
        probe.conclude(
            "exactly the seven documented fields, in the documented order, with the documented "
            "shapes — measured with no token on the pinned line",
            matches_documentation=True,
        )
    return probe


if __name__ == "__main__":
    raise SystemExit(main(run, __doc__.splitlines()[0]))
