#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Extract the reference's JSON property names into a committed index.

The alias sweep asks one question of every field this project serialises: is this exactly a
property name the reference uses? Answering it needs the reference's names, and the pinned OpenAPI
document is fetched rather than vendored - so CI, which has no Jellyfin to fetch from, would have
to skip the sweep. A skipping sweep has exactly the same effect as an unwritten one.

So the names are extracted once into `docs/compatibility/property-names.json` and committed. The
index is this project's own extraction, it needs no network, and it turns the sweep into a hard
gate. When the pinned document is available, `--check` verifies the index still matches it.

Usage:
    python3 tools/extract_property_names.py --spec reference/openapi.json
    python3 tools/extract_property_names.py --spec reference/openapi.json --check

Exit code 0 when the index was written, or (under --check) still matches. 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

DEFAULT_INDEX = Path("docs/compatibility/property-names.json")

HEADER = (
    "Property names used by the pinned Jellyfin OpenAPI document, extracted by "
    "tools/extract_property_names.py. Regenerate with --check in CI; never edit by hand. "
    "See specs/001-server-identity-and-discovery/plan.md section 8.3."
)


def collect(spec: dict[str, Any]) -> list[str]:
    """Every distinct property name across every schema, sorted."""
    names: set[str] = set()
    for schema in spec.get("components", {}).get("schemas", {}).values():
        if isinstance(schema, dict):
            names.update(k for k in schema.get("properties", {}) if isinstance(k, str))
    return sorted(names)


def build(spec: dict[str, Any]) -> dict[str, Any]:
    names = collect(spec)
    return {
        "_comment": HEADER,
        "reference_version": spec.get("info", {}).get("version", "unknown"),
        "count": len(names),
        "names": names,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--spec", required=True, type=Path, help="Pinned OpenAPI document")
    parser.add_argument("--index", default=DEFAULT_INDEX, type=Path)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify the committed index matches the document; write nothing",
    )
    args = parser.parse_args()

    try:
        spec = json.loads(args.spec.read_text(encoding="utf-8"))
    except OSError as exc:
        print(f"cannot read the pinned document: {exc}", file=sys.stderr)
        return 1

    fresh = build(spec)

    if args.check:
        if not args.index.is_file():
            print(f"{args.index} does not exist; run without --check to create it", file=sys.stderr)
            return 1
        current = json.loads(args.index.read_text(encoding="utf-8"))
        if current.get("names") == fresh["names"] and current.get("reference_version") == fresh.get(
            "reference_version"
        ):
            print(f"{args.index}: {fresh['count']} names, matches {args.spec}")
            return 0

        missing = sorted(set(fresh["names"]) - set(current.get("names", [])))
        extra = sorted(set(current.get("names", [])) - set(fresh["names"]))
        print(f"error: {args.index} is stale", file=sys.stderr)
        if current.get("reference_version") != fresh.get("reference_version"):
            print(
                f"  version: index says {current.get('reference_version')}, "
                f"document says {fresh.get('reference_version')}",
                file=sys.stderr,
            )
        for name in missing[:10]:
            print(f"  in the document, not in the index: {name}", file=sys.stderr)
        for name in extra[:10]:
            print(f"  in the index, not in the document: {name}", file=sys.stderr)
        if len(missing) + len(extra) > 20:
            print(f"  ... and {len(missing) + len(extra) - 20} more", file=sys.stderr)
        return 1

    args.index.parent.mkdir(parents=True, exist_ok=True)
    args.index.write_text(json.dumps(fresh, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {args.index}: {fresh['count']} names from {fresh['reference_version']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
