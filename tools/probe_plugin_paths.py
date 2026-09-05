#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Which of the paths in the document a reference server serves come from its plugins?

A Jellyfin's OpenAPI document is the core API **plus whatever plugins that server has installed**.
That is the claim [reference-target.md](../docs/compatibility/reference-target.md) section 1 and
[ADR-0007](../docs/decisions/0007-a-container-runtime-for-the-reference-instance.md) both rest on,
and it is not a small one: it is why nineteen Trakt.tv property names lived in
`docs/compatibility/property-names.json` for the life of the project, extracted from one
differently configured server's document and invisible to every check that ran without one, and it
is one of ADR-0007's reasons for standing up a pinned instance instead of asking each contributor
to install a Jellyfin by hand.

The claim was measured by hand on 2026-09-01, and its citation named these two endpoints rather
than a script - so nothing re-runnable resolved from it. This script is the one that citation
never had (the L4 fold of the 2026-09-04 audit, the class the 2026-08-28 audit closed for ~25
other occurrences).

**The attribution is by name, and it is a lower bound.** Nothing in the document says which
component declared a path, so this probe folds each installed plugin's name to letters and digits
and matches it against the first segment of every declared path: `TMDb Box Sets` claims
`/TMDbBoxSets/Refresh`, `TMDb` claims `/Tmdb/ClientConfiguration`. A plugin whose routes are named
after something other than itself would be missed, which is why the finding is stated as *at
least* - and why every plugin that claimed nothing is reported by name rather than passed over.
The claim needs only that the intersection is not empty: one plugin-contributed path is enough to
make a count taken from a fetched document a fact about that server rather than about Jellyfin.

Read-only: two `GET`s, and the second one is the document itself. `/Plugins` needs an
administrator - the controller is `Policies.RequiresElevation`
`[source: Jellyfin.Api/Controllers/PluginsController.cs:25 @ v10.11.11]` - so an ordinary account
cannot answer this question and the probe says so rather than reporting an empty list.

Writes: nothing.

Usage:
    python3 tools/probe_plugin_paths.py http://your-jellyfin:8096 -u administrator
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any, Dict, List, Set, Tuple

from _probe import Probe, ProbeError, Server, main

SPEC_PATH = "/api-docs/openapi.json"

#: Everything that is not a letter or a digit, so `TMDb Box Sets` and `TMDbBoxSets` fold together.
NOISE = re.compile(r"[^a-z0-9]+")

EXPECTATION = (
    "reference-target.md section 1 and ADR-0007: the OpenAPI document a reference server serves "
    "is the core API plus that server's plugins, so at least one of its declared paths is "
    "contributed by an installed plugin - on 2026-09-01 that was two of 316 paths, from a server "
    "carrying six plugins"
)


def fold(name: str) -> str:
    return NOISE.sub("", name.lower())


def document(server: Server) -> Dict[str, Any]:
    """The document this server serves, fetched the way `fetch_reference_spec.py` fetches it.

    Unauthenticated on purpose: the route needs no token, and reading it as the administrator
    whose token answered `/Plugins` would leave open whether the two readings saw the same
    document. Sanitising it is `fetch_reference_spec.py`'s job and would change nothing counted
    here - both passes rewrite response bodies, neither adds or removes a path.
    """
    url = server.base + SPEC_PATH
    try:
        # S310: the operator's own server, the same base every other request here uses.
        with urllib.request.urlopen(url, timeout=server.timeout) as response:  # noqa: S310
            return dict(json.loads(response.read()))
    except (urllib.error.URLError, ValueError, OSError) as failure:
        raise ProbeError(
            f"GET {SPEC_PATH} -> {failure}. Without the document there is nothing to attribute; "
            f"this is the route tools/fetch_reference_spec.py reads."
        ) from failure


def plugins(server: Server) -> List[Dict[str, Any]]:
    """`GET /Plugins`, and a `403` here is a wrong account rather than a wrong claim."""
    try:
        rows = server.get("/Plugins")
    except ProbeError as failure:
        if failure.status in (401, 403):
            raise ProbeError(
                "GET /Plugins refused this account. The controller requires elevation "
                "`[source: Jellyfin.Api/Controllers/PluginsController.cs:25 @ v10.11.11]`, so "
                "this question needs an administrator - an ordinary account would report an "
                "empty plugin list and turn a refusal into a measurement."
            ) from failure
        raise
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def first_segment(path: str) -> str:
    return path.strip("/").split("/")[0] if path.strip("/") else ""


def attribute(paths: List[str], installed: List[Dict[str, Any]]) -> Tuple[Dict[str, str], Set[str]]:
    """Which paths a plugin's name claims, and which plugins claimed nothing.

    Returns `{path: plugin name}` and the set of plugin names that matched no path. Both halves
    are reported: the second is what makes the finding a lower bound out loud instead of in a
    comment nobody reads.
    """
    by_fold = {fold(str(row.get("Name", ""))): str(row.get("Name", "")) for row in installed}
    by_fold.pop("", None)
    claimed: Dict[str, str] = {}
    for path in paths:
        owner = by_fold.get(fold(first_segment(path)))
        if owner is not None:
            claimed[path] = owner
    silent = set(by_fold.values()) - set(claimed.values())
    return claimed, silent


def run(server: Server) -> Probe:
    probe = Probe(
        script="probe_plugin_paths.py",
        question="which of the paths in this server's OpenAPI document come from its plugins?",
        document="docs/compatibility/reference-target.md",
        section="section 1",
        expectation=EXPECTATION,
    )

    installed = plugins(server)
    if not installed:
        raise ProbeError(
            "this server has no plugins installed, so it cannot answer whether a plugin "
            "contributes a path to the document. That is not a contradiction of the claim - it "
            "is a server that happens to be the core API on its own, which is exactly the state "
            "ADR-0007's pinned instance exists to make reproducible. Point this probe at the "
            "server whose document the count under measurement was taken from."
        )

    body = document(server)
    paths = sorted(str(path) for path in (body.get("paths") or {}))
    if not paths:
        raise ProbeError(f"{SPEC_PATH} declares no paths, so there is nothing to attribute")

    claimed, silent = attribute(paths, installed)

    probe.observe(
        "plugins installed",
        f"{len(installed)}: "
        + ", ".join(sorted(f"{row.get('Name')} {row.get('Version')}".strip() for row in installed)),
    )
    probe.observe("paths the document declares", len(paths))
    probe.observe(
        "paths a plugin's name claims",
        f"{len(claimed)}: "
        + (", ".join(f"{path} ({owner})" for path, owner in sorted(claimed.items())) or "none"),
    )
    probe.observe(
        "plugins claiming no path",
        ", ".join(sorted(silent)) or "none - every installed plugin names at least one path",
    )
    probe.observe(
        "operations the document declares",
        sum(
            1
            for path in paths
            for key in (body.get("paths") or {}).get(path, {})
            if key.lower() in ("get", "put", "post", "delete", "patch", "head", "options", "trace")
        ),
    )

    contributed = bool(claimed)
    probe.conclude(
        (
            f"the document this server serves is the core API plus its own plugins: "
            f"{len(claimed)} of {len(paths)} declared paths are named after one of the "
            f"{len(installed)} installed plugins ("
            + ", ".join(sorted(claimed))
            + "). A path count, an operation count or a property extraction taken from a fetched "
            "document is therefore a fact about this server and not about Jellyfin"
            if contributed
            else f"none of the {len(paths)} declared paths is named after any of the "
            f"{len(installed)} installed plugins, so this run found no evidence that a plugin "
            f"contributes a path here. Either these plugins serve no routes, or they serve them "
            f"under names this probe's attribution cannot see - and the second would mean the "
            f"attribution is wrong rather than the claim"
        ),
        matches_documentation=contributed,
    )
    probe.note(
        "The attribution is by name and is a lower bound: nothing in the document records which "
        "component declared a path, so a plugin routing under some other word would not be "
        "counted. The claim needs only that the intersection is non-empty, which is why the "
        "plugins that claimed nothing are listed rather than treated as a failure."
    )
    probe.note(
        "The counts are one server's reading on one day. What is durable is the shape: "
        "reference-target.md section 1 records the nineteen Trakt.tv property names that reached "
        "docs/compatibility/property-names.json from an earlier, differently configured server "
        "and survived every check that ran without a document. Check /Plugins before treating a "
        "fetched document, or any number derived from one, as a fact about Jellyfin."
    )
    return probe


if __name__ == "__main__":
    raise SystemExit(main(run, __doc__.splitlines()[0]))
