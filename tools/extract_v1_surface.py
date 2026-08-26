#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Validate docs/compatibility/surface.yaml against the pinned Jellyfin OpenAPI document.

This is the automated half of Principle VI ("implement what is actually called"). It answers
one question: does every endpoint Atrium claims to serve actually exist in the contract it
claims to implement?

It checks, for every entry in the surface file:

  * the `level` is one of L0..L3;
  * the path is absolute and the method is an HTTP method;
  * no (path, method) pair appears twice;
  * the pinned document version is recorded, and the document given is that version;

and, **when a document is given**:

  * the path exists in the OpenAPI document;
  * the method exists on that path;
  * the recorded `operation` matches the document's `operationId`.

The document is fetched rather than vendored, so CI has none - and a tool that refuses to run
without one is a tool CI does not run. Without `--spec` it does everything that needs no document
and **says, in the last line, which checks did not happen**. Silence there would read as a pass.

It does NOT check that the server implements them - that is the route-registration test, which
reads the same file.

Usage:
    python3 tools/extract_v1_surface.py                                   # no document needed
    python3 tools/extract_v1_surface.py --spec reference/openapi.json
    python3 tools/extract_v1_surface.py --spec reference/openapi.json --print-summary

Exit code 0 when the surface is consistent with the contract, 1 otherwise. Intended to run in
CI so that docs/compatibility/api-surface-v1.md cannot silently drift from the pinned document.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

LEVELS = {"L0", "L1", "L2", "L3"}

DEFAULT_SURFACE = Path("docs/compatibility/surface.yaml")

# The surface file is a deliberately flat subset of YAML - a `reference:` mapping and an
# `endpoints:` list of single-level mappings. Parsing it with a few regexes keeps this tool
# dependency-free, which matters because it runs in CI before any environment is built.
_ENTRY_START = re.compile(r'^\s*-\s+path:\s*"([^"]+)"\s*$')
# Two spaces or more: the reference block is indented by two and an endpoint's fields by four.
# This read `\s{4}` until 2026-08-26, which matched the endpoints and silently dropped every
# reference field - so the version gate below had never once run. A check that cannot fail is a
# check that will not happen, which is why `main` now refuses a surface file with no reference
# block rather than treating it as one that pins nothing.
_FIELD = re.compile(r"^\s{2,}(\w+):\s*(.+?)\s*$")


def parse_surface(text: str) -> tuple[dict[str, str], list[dict[str, str]]]:
    reference: dict[str, str] = {}
    endpoints: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    section: str | None = None

    for raw in text.splitlines():
        line = raw.split("#", 1)[0] if raw.lstrip().startswith("#") else raw
        if not line.strip():
            continue
        if line.startswith("reference:"):
            section, current = "reference", None
            continue
        if line.startswith("endpoints:"):
            section, current = "endpoints", None
            continue

        start = _ENTRY_START.match(line)
        if start:
            current = {"path": start.group(1)}
            endpoints.append(current)
            continue

        field = _FIELD.match(line)
        if not field:
            continue
        key, value = field.group(1), field.group(2).strip().strip('"')
        if section == "reference" and current is None:
            reference[key] = value
        elif current is not None:
            current[key] = value

    return reference, endpoints


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--spec",
        type=Path,
        help="Pinned OpenAPI document. Without it, only the checks that need no document run - "
        "which is what CI has, since the document is fetched rather than vendored",
    )
    parser.add_argument("--surface", default=DEFAULT_SURFACE, type=Path)
    parser.add_argument("--print-summary", action="store_true")
    args = parser.parse_args()

    spec = json.loads(args.spec.read_text(encoding="utf-8")) if args.spec else None
    paths = spec.get("paths", {}) if spec else {}
    reference, endpoints = parse_surface(args.surface.read_text(encoding="utf-8"))

    spec_version = spec.get("info", {}).get("version") if spec else None
    pinned = reference.get("jellyfin_openapi_version")
    errors: list[str] = []

    if not endpoints:
        errors.append(f"{args.surface} has no endpoints; the parser and the file disagree")

    if not pinned:
        errors.append(
            f"{args.surface} has no reference.jellyfin_openapi_version. The version gate cannot "
            f"run without it, and a gate that cannot run is worse than no gate"
        )
    elif spec_version is not None and spec_version != pinned:
        errors.append(
            f"version mismatch: surface pins {pinned}, document is {spec_version}. "
            f"Moving the pin has a procedure - see docs/compatibility/conformance.md"
        )

    seen = Counter((e.get("method"), e.get("path")) for e in endpoints)
    for key, count in seen.items():
        if count > 1:
            errors.append(f"duplicate entry: {key[0]} {key[1]} appears {count} times")

    for entry in endpoints:
        path, method = entry.get("path", "?"), entry.get("method", "?")
        where = f"{method} {path}"

        if entry.get("level") not in LEVELS:
            errors.append(f"{where}: level {entry.get('level')!r} is not one of {sorted(LEVELS)}")

        if not path.startswith("/"):
            errors.append(f"{where}: a path is absolute or it is a typo")
        if method != method.upper() or not method.isalpha():
            errors.append(f"{where}: {method!r} is not an HTTP method")

        if spec is None:
            continue

        node = paths.get(path)
        if node is None:
            errors.append(f"{where}: path not present in the pinned document")
            continue

        operation = node.get(method.lower())
        if operation is None:
            available = ", ".join(sorted(m.upper() for m in node if m != "parameters")) or "none"
            errors.append(f"{where}: method not present (document has: {available})")
            continue

        expected = operation.get("operationId")
        if entry.get("operation") != expected:
            errors.append(
                f"{where}: operation is {entry.get('operation')!r}, document says {expected!r}"
            )

    if args.print_summary and not errors:
        by_feature: Counter[str] = Counter(e.get("feature", "?") for e in endpoints)
        by_level: Counter[str] = Counter(e.get("level", "?") for e in endpoints)
        print(f"{len(endpoints)} endpoints against Jellyfin {spec_version or pinned}")
        print("  by feature: " + ", ".join(f"{k}={v}" for k, v in sorted(by_feature.items())))
        print("  by level:   " + ", ".join(f"{k}={v}" for k, v in sorted(by_level.items())))

    for error in errors:
        print(f"error: {error}", file=sys.stderr)

    if errors:
        print(f"\n{len(errors)} problem(s) in {args.surface}", file=sys.stderr)
        return 1

    if spec is None:
        # Named, not counted: a reader has to be able to tell "everything passed" from "the half
        # that needs the contract did not run". The other half is the point of the tool.
        print(
            f"{args.surface}: {len(endpoints)} endpoints are internally consistent. "
            f"Paths, methods and operation ids were NOT checked - no document was given. "
            f"Fetch one with tools/fetch_reference_spec.py and pass --spec."
        )
        return 0

    print(f"{args.surface}: {len(endpoints)} endpoints consistent with {args.spec}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
