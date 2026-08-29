#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""What does the reference call a file's container, and what decides the single form?

008 spec section 3.1 said two things about this, and a library with five file extensions in it
contradicts both:

- *"Item-level `Container` is a demuxer list, not a container."* It is a list for the mp4 family
  and a single word for everything else. A `.mkv` answers `mkv`.
- *"The source's own `Container` is only resolved against a profile."* On a listing no profile is
  involved at all: the single form is the **file's extension**, taken when it is one of the
  members of the list, and the reference's own code falls back to the list's first member when it
  is not.

The distinction is the reason 008 T2 stores one container column rather than two. A "resolved
single container" is not a property of a file - the same bytes answer `mp4` on `/Items` and the
whole six-member list on a profile-less negotiation - so what inspection can store is the
normalised list, and the single form is derived per response by whatever is emitting it.

Read-only: it lists items and asks one negotiation question, and reserves nothing.

Usage:
    python3 tools/probe_media_container.py http://your-jellyfin:8096 -u admin
"""

from __future__ import annotations

import collections
from typing import Any, Dict, List, Optional, Tuple

from _probe import Probe, ProbeError, Server, main

#: The item types that have files behind them. A container item has no media source at all, so
#: including one would only add empty rows.
TYPES = ("Movie", "Episode", "Audio")

#: How many of each to look at. The question is about extensions rather than items, and a library
#: holds a handful of extensions however many files it has.
SAMPLE = 400


def _extension(path: str) -> str:
    tail = path.rsplit("/", 1)[-1]
    return tail.rsplit(".", 1)[-1].lower() if "." in tail else "(none)"


def _sample(server: Server) -> List[Dict[str, Any]]:
    found: List[Dict[str, Any]] = []
    for kind in TYPES:
        page = server.get_where(
            "/Items",
            {
                "userId": server.user_id,
                "recursive": "true",
                "includeItemTypes": kind,
                "fields": "Container,MediaSources,Path",
                "limit": SAMPLE,
            },
        )
        found.extend(page.get("Items") or [])
    if not found:
        raise ProbeError("no items with files were returned; is the library empty?")
    return found


def _by_extension(items: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """One row per file extension: what the item said, what its sources said, how many."""
    rows: Dict[str, Dict[str, Any]] = {}
    for item in items:
        path = item.get("Path") or ""
        if not path:
            continue
        row = rows.setdefault(
            _extension(path),
            {"item": collections.Counter(), "source": collections.Counter(), "example": None},
        )
        row["item"][item.get("Container")] += 1
        for source in item.get("MediaSources") or []:
            row["source"][source.get("Container")] += 1
        if row["example"] is None:
            row["example"] = item
    return rows


def _expected_source(item_level: Optional[str], extension: str) -> Tuple[Optional[str], str]:
    """What the source's container should be if the rule holds, and which half of it applied.

    The reason is printed beside the value, so a row that disagrees names the branch it broke
    rather than only the string it saw.
    """
    if not item_level or "," not in item_level:
        return item_level, "no list to resolve, so the source repeats the item's container"
    members = item_level.split(",")
    if extension in members:
        return extension, "the extension is one of the members, so the extension wins"
    return members[0], "the extension is not a member, so the first member wins"


def run(server: Server) -> Probe:
    probe = Probe(
        script="probe_media_container.py",
        question="what is a file's Container at item level and on its media source, and what "
        "decides the single form?",
        document="specs/008-playback-negotiation-and-delivery/spec.md",
        section="section 3.1",
        expectation=(
            "the item-level Container is the reference's normalised container string - a "
            "demuxer list for the mp4 family, a single name for the rest; the source's single "
            "container on a listing is the file's extension where the list contains it, with no "
            "profile involved; and a profile-less negotiation reports the list on the source too"
        ),
    )

    rows = _by_extension(_sample(server))
    checks: List[bool] = []
    lists_seen = 0
    singles_seen = 0

    for extension in sorted(rows):
        row = rows[extension]
        item_levels = sorted(str(one) for one in row["item"])
        source_levels = sorted(str(one) for one in row["source"])
        total = sum(row["item"].values())
        probe.observe(
            "." + extension,
            f"{total:>4} item(s)   item-level {'/'.join(item_levels)}   "
            f"source {'/'.join(source_levels)}",
        )

        item_level = next(iter(row["item"]))
        if item_level and "," in item_level:
            lists_seen += 1
        else:
            singles_seen += 1
        expected, reason = _expected_source(item_level, extension)
        checks.append(list(row["source"]) == [expected])
        probe.observe("  rule", f"{item_level} -> {expected}   ({reason})")

    probe.observe("shapes", f"{lists_seen} extension(s) list-valued, {singles_seen} single")
    checks.append(lists_seen > 0 and singles_seen > 0)

    listed = next(
        (rows[one]["example"] for one in sorted(rows) if "," in str(next(iter(rows[one]["item"])))),
        None,
    )
    if listed is not None:
        negotiated = server.get(f"/Items/{listed['Id']}/PlaybackInfo", userId=server.user_id)
        sources = negotiated.get("MediaSources") or [{}]
        on_the_listing = (listed.get("MediaSources") or [{}])[0].get("Container")
        probe.observe(
            "same item, no profile",
            f"PlaybackInfo source Container {sources[0].get('Container')!r} "
            f"against listing {on_the_listing!r}",
        )
        checks.append(sources[0].get("Container") == listed.get("Container"))
        probe.note(
            "The same file, two routes, two answers: a listing resolves the demuxer list to one "
            "member by the file's extension, and a negotiation with no device profile leaves the "
            "list alone. Neither answer is a property of the file, which is why inspection stores "
            "the normalised list and nothing else (008 plan section 4)."
        )

    probe.conclude(
        "the item-level Container is a demuxer list for some formats and a single name for "
        "others; the single form a media source reports is derived per response - from the "
        "file's extension on a listing, and from the device profile in a negotiation, which "
        "leaves the list untouched when there is no profile",
        matches_documentation=all(checks),
    )
    return probe


if __name__ == "__main__":
    raise SystemExit(
        main(run, "What does the reference call a file's container, and what decides it?")
    )
