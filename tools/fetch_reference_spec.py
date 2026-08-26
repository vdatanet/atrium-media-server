#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Fetch and sanitise the Jellyfin OpenAPI document that Atrium is specified against.

The document is deliberately NOT vendored into this repository: it is generated from
GPL-licensed source, and vendoring it would drag a licensing question into a repository that
does not need one (see docs/decisions/0005-licence.md). Fetch it into the git-ignored
`reference/` directory instead.

Usage:
    python3 tools/fetch_reference_spec.py http://your-jellyfin:8096
    python3 tools/fetch_reference_spec.py http://your-jellyfin:8096 --out reference/openapi.json

Two sanitising passes are applied, and each exists because the raw document is not directly
usable:

  1. `strip_allow_empty_value_in_headers` - Jellyfin's 503 responses declare `Retry-After` and
     `Message` headers with `allowEmptyValue`, a property valid on Parameter objects but not on
     Header objects. Strict parsers reject the whole document over it.

  2. `collapse_profile_content_types` - every JSON response is declared three times:
     `application/json`, `application/json; profile="CamelCase"` and `; profile="PascalCase"`,
     all pointing at the same schema. The variants add nothing and make tooling output
     unreadable.

Both are recorded in docs/compatibility/reference-target.md as reasons the OpenAPI document
ranks *below* a running server as a source of truth.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path
from typing import Any

SPEC_PATH = "/api-docs/openapi.json"


def strip_allow_empty_value_in_headers(node: Any, parent_key: str | None = None) -> int:
    """Remove `allowEmptyValue` from Header objects. Returns the number removed."""
    removed = 0
    if isinstance(node, dict):
        if parent_key == "headers":
            for header in node.values():
                if isinstance(header, dict) and "allowEmptyValue" in header:
                    del header["allowEmptyValue"]
                    removed += 1
        for key, value in node.items():
            removed += strip_allow_empty_value_in_headers(value, key)
    elif isinstance(node, list):
        for item in node:
            removed += strip_allow_empty_value_in_headers(item, parent_key)
    return removed


def collapse_profile_content_types(node: Any, parent_key: str | None = None) -> int:
    """Drop `; profile=...` duplicates from `content` maps when a base type is present."""
    removed = 0
    if isinstance(node, dict):
        if parent_key == "content":
            base = next((k for k in node if "profile=" not in k.lower()), None)
            if base is not None:
                for key in [k for k in node if "profile=" in k.lower()]:
                    del node[key]
                    removed += 1
        for key, value in list(node.items()):
            removed += collapse_profile_content_types(value, key)
    elif isinstance(node, list):
        for item in node:
            removed += collapse_profile_content_types(item, parent_key)
    return removed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("server", help="Base URL of a running Jellyfin, e.g. http://host:8096")
    parser.add_argument("--out", default="reference/openapi.json", type=Path)
    parser.add_argument("--raw", action="store_true", help="Skip the sanitising passes")
    args = parser.parse_args()

    url = args.server.rstrip("/") + SPEC_PATH
    print(f"fetching {url}", file=sys.stderr)
    with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310 - operator-supplied URL
        spec = json.load(response)

    version = spec.get("info", {}).get("version", "unknown")
    print(f"  Jellyfin API version: {version}", file=sys.stderr)
    print(f"  paths: {len(spec.get('paths', {}))}", file=sys.stderr)
    print(f"  schemas: {len(spec.get('components', {}).get('schemas', {}))}", file=sys.stderr)

    if not args.raw:
        headers = strip_allow_empty_value_in_headers(spec)
        profiles = collapse_profile_content_types(spec)
        print(f"  removed {headers} allowEmptyValue, {profiles} profile content types", file=sys.stderr)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
