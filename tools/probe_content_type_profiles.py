#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Does the server answer the three declared JSON content types identically?

Every operation in the reference's OpenAPI document declares three response content types:
`application/json`, `application/json; profile="PascalCase"` and
`application/json; profile="CamelCase"`. Reading that list, this project concluded they were three
names for one behaviour and wrote it into specs/001 section 3.0 rule 2 and acceptance criterion 9.

They are three names for **two** behaviours. The profile selects an output formatter, and the
camelCase one really does emit camelCase property names - so a client that asks for it and is
served PascalCase gets an empty object out of its decoder.

The probe asks three things about the same endpoint, in one question:

1. **What comes back** for each of the three declared content types - status, `Content-Type`,
   property casing, and whether the bytes are identical.
2. **How the match is made** - quoting, casing and extra parameters on the request's `Accept`,
   because whoever implements the profile has to reproduce the matching rule and not only the
   output.
3. **What the conversion rule is** - best effort, from whatever the credentials can reach. Two
   details decide a correct implementation: dictionary *keys* are not converted, and a leading
   run of capitals converts as .NET's policy does rather than by lowering the first letter.

Read-only. Writes nothing.

Usage:
    python3 tools/probe_content_type_profiles.py http://your-jellyfin:8096 -u username
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from _probe import Probe, ProbeError, Server, main

PATH = "/System/Info/Public"

PLAIN = "application/json"
PASCAL = 'application/json; profile="PascalCase"'
CAMEL = 'application/json; profile="CamelCase"'

#: The declared three, in the order the document lists them.
DECLARED = [PLAIN, PASCAL, CAMEL]

#: Spellings a client might plausibly send, to find where the match stops working.
TOLERANCE = [
    'application/json;profile="CamelCase"',  # no space after the semicolon
    "application/json; profile=CamelCase",  # unquoted
    'application/json; profile="camelcase"',  # lowercased value
    'application/json; charset=utf-8; profile="CamelCase"',  # an extra parameter
    'application/json, application/json; profile="CamelCase"',  # two, equal quality
    'application/json;q=0.5, application/json; profile="CamelCase";q=0.9',  # two, ranked
    'application/json; profile="Nonsense"',  # a profile that does not exist
]


def request(server: Server, path: str, accept: str) -> tuple[int, str, bytes]:
    """One GET with a chosen `Accept`, returning status, content type and raw body.

    `Server.get_raw` sends the harness's own `Accept`, and the header under measurement is the
    whole question here, so this issues the request directly.
    """
    url = server.base + path
    headers = {"Accept": accept}
    if server.token:
        headers["X-Emby-Token"] = server.token
    # S310: the URL is the operator's own server, given on the command line or in .env.
    req = urllib.request.Request(url, headers=headers, method="GET")  # noqa: S310
    try:
        with urllib.request.urlopen(req, timeout=server.timeout) as response:  # noqa: S310
            return response.status, response.headers.get("Content-Type", ""), response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get("Content-Type", ""), exc.read()
    except urllib.error.URLError as exc:
        raise ProbeError(f"GET {path} -> {exc.reason}") from exc


def casing_of(body: bytes) -> str:
    """Which casing the property names in a JSON object use."""
    try:
        document = json.loads(body)
    except json.JSONDecodeError:
        return "not JSON"
    if not isinstance(document, dict) or not document:
        return "no properties"
    first = next(iter(document))
    if first[:1].isupper():
        return "PascalCase"
    if first[:1].islower():
        return "camelCase"
    return "neither"


def naive(name: str) -> str:
    """The obvious conversion: lower the first letter and keep the rest."""
    return name[:1].lower() + name[1:]


def property_names(node: Any, out: list[str]) -> None:
    """Every property name in a document, depth first, in serialisation order."""
    if isinstance(node, dict):
        for key, value in node.items():
            out.append(key)
            property_names(value, out)
    elif isinstance(node, list):
        for value in node[:1]:
            property_names(value, out)


def conversions(server: Server, path: str) -> list[tuple[str, str]] | None:
    """Pair each PascalCase name in a document with its camelCase counterpart, in order.

    Returns None when the document is not reachable with these credentials - an unavailable
    observation, not a finding.
    """
    try:
        _, _, pascal = request(server, path, PASCAL)
        _, _, camel = request(server, path, CAMEL)
        left: list[str] = []
        right: list[str] = []
        property_names(json.loads(pascal), left)
        property_names(json.loads(camel), right)
    except (ProbeError, json.JSONDecodeError):
        return None
    if len(left) != len(right):
        return None
    # B905: `strict=` arrived in 3.10 and these run on 3.9. The lengths are compared above,
    # which is the same guarantee written where a reader can check it.
    return list(zip(left, right))  # noqa: B905


def run(server: Server) -> Probe:
    probe = Probe(
        script="probe_content_type_profiles.py",
        question="does the server answer the three declared JSON content types identically?",
        document="specs/001-server-identity-and-discovery/spec.md",
        section="section 3.0 rule 2",
        expectation=(
            'the three declared content types are answered with two behaviours: profile="CamelCase"'
            " emits camelCase property names, the other two emit PascalCase, and the response's "
            "Content-Type echoes the profile that was matched"
        ),
    )

    bodies: dict[str, bytes] = {}
    for accept in DECLARED:
        status, content_type, body = request(server, PATH, accept)
        if status != 200:
            raise ProbeError(f"GET {PATH} with Accept: {accept} -> HTTP {status}")
        bodies[accept] = body
        probe.observe(f"Accept: {accept}", f"{casing_of(body):10}  Content-Type: {content_type}")

    identical = len(set(bodies.values())) == 1
    camel_differs = bodies[CAMEL] != bodies[PLAIN]
    pascal_matches_plain = bodies[PASCAL] == bodies[PLAIN]

    for accept in TOLERANCE:
        _, content_type, body = request(server, PATH, accept)
        matched = "profile=" in content_type.replace(" ", "").lower()
        probe.observe(
            f"Accept: {accept}",
            f"{casing_of(body):10}  {'matched a profile' if matched else 'fell back to plain'}",
        )

    # How names are converted. Two documents, both best effort: the first carries the dictionaries
    # (`ProviderIds`, `ImageTags`), the second carries `UICulture`, the only name in the pinned
    # document where .NET's policy and "lower the first letter" disagree.
    for label, path, needs_user in (
        ("dictionary keys", "/Items?Limit=1&Recursive=true&Fields=ProviderIds,ImageTags", True),
        ("leading acronyms", "/System/Configuration", False),
    ):
        if needs_user and server.user_id:
            path += "&UserId=" + urllib.parse.quote(server.user_id)
        paired = conversions(server, path)
        if paired is None:
            probe.note(
                f"{label}: {path.split('?')[0]} was not reachable with these credentials, so this "
                "part of the rule was not measured on this run."
            )
            continue
        irregular = [(left, right) for left, right in paired if right != naive(left)]
        if not irregular:
            probe.note(f"{label}: every one of the {len(paired)} names lowered its first letter.")
            continue
        unchanged = [left for left, right in irregular if left == right]
        other = [f"{left} -> {right}" for left, right in irregular if left != right]
        detail = []
        if unchanged:
            detail.append(f"{len(unchanged)} name(s) not converted at all ({', '.join(unchanged)})")
        if other:
            detail.append("; ".join(other))
        probe.note(f"{label}: " + "; ".join(detail))

    probe.note(
        "The two rules a correct implementation needs: property names are converted at every "
        "depth, and dictionary keys are not converted at all - the reference sets "
        "PropertyNamingPolicy and never sets DictionaryKeyPolicy. "
        "[source: src/Jellyfin.Extensions/Json/JsonDefaults.cs:55-58 @ v10.11.11]"
    )

    if identical:
        probe.conclude(
            "all three content types returned byte-identical bodies - the profile selects nothing",
            matches_documentation=False,
        )
    elif camel_differs and pascal_matches_plain:
        probe.conclude(
            'profile="CamelCase" returns camelCase property names while application/json and '
            'profile="PascalCase" return PascalCase, and the Content-Type echoes the matched '
            "profile. Three declared content types, two behaviours",
            matches_documentation=True,
        )
    else:
        probe.conclude(
            f"an unexpected split: camelCase differs from plain: {camel_differs}; "
            f"PascalCase equals plain: {pascal_matches_plain}",
            matches_documentation=False,
        )
    return probe


if __name__ == "__main__":
    raise SystemExit(main(run, __doc__.splitlines()[0]))
