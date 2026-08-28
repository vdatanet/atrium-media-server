#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""What exactly does `GET /System/Info/Public` return, before any token exists?

Discharges the prior-probe on the payload recorded in
docs/compatibility/reference-target.md §6 and specs/001 §3.1: the seven fields, their order, and
their shapes were carried forward from a pre-repository measurement (2026-06-13) that nothing
here could re-run. This is the re-run.

Read-only, and unauthenticated for the headline question: the point of the route is that it
answers with no token, so the probe sends none there.

When credentials are given it also makes one authenticated request to `/System/Info`, for the
example behaviours section 1.7 rests on: the schema declares `PackageName` and the body does not
carry it, because the reference's JSON pipeline omits any null property. That claim was
hand-measured on 2026-08-26 and folded here on 2026-08-28 (the L2 pattern of
docs/audits/2026-08-28.md).

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


def declared_system_info_properties(server: Server) -> set[str] | None:
    """The SystemInfo schema's property names from the server's own OpenAPI document, if any.

    It is the 'declares' half of behaviours section 1.7's example; the 'does not send' half is
    the body itself.
    """
    url = server.base + "/api-docs/openapi.json"
    try:
        # S310: operator-supplied URL, the same one every other request here uses.
        with urllib.request.urlopen(url, timeout=server.timeout) as response:  # noqa: S310
            document = json.loads(response.read())
    except (urllib.error.URLError, ValueError, OSError):
        return None
    schema = document.get("components", {}).get("schemas", {}).get("SystemInfo", {})
    properties = schema.get("properties")
    return set(properties) if isinstance(properties, dict) else None


def run(server: Server) -> Probe:
    probe = Probe(
        script="probe_public_info.py",
        question="what exactly does /System/Info/Public return, before any token exists?",
        document="specs/001-server-identity-and-discovery/spec.md",
        section="section 3.1",
        expectation=(
            "200 with exactly LocalAddress, ServerName, Version, ProductName, OperatingSystem, "
            "Id, StartupWizardCompleted in that order; ProductName is 'Jellyfin Server', "
            "OperatingSystem is '', Id is 32 lowercase hex; and the authenticated /System/Info "
            "declares PackageName in its schema and does not send it (behaviours section 1.7)"
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

    # -- behaviours 1.7's example: /System/Info declares PackageName and does not send it ------
    if server.token:
        info = server.get("/System/Info")
        declared = declared_system_info_properties(server)
        sent = "PackageName" in info
        in_schema = declared is None or "PackageName" in declared
        probe.observe(
            "PackageName",
            ("declared in the SystemInfo schema" if in_schema else "NOT in the SystemInfo schema")
            + (", sent in the body" if sent else ", absent from the body"),
        )
        if declared is None:
            probe.note(
                "the SystemInfo schema could not be read from the server's OpenAPI document, so "
                "'declared' rests on the pinned document rather than this run."
            )
        if sent or not in_schema:
            problems.append(
                "behaviours section 1.7's example did not reproduce: PackageName should be "
                "declared and not sent"
            )
    else:
        probe.note(
            "the PackageName half was NOT measured: /System/Info needs a token, and this run "
            "had none. Run with credentials to measure it."
        )

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
