#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""What does a media source carry on a listing, and where does its `ETag` come from?

008 spec section 3.1 names five groups of fields a source carries and says nothing about how the
`ETag` is derived; plan section 6.8 books that derivation as a debt for the task that emits it.
This probe discharges both halves.

**The `ETag` is not the hexadecimal of an MD5 digest**, which is what reading the assignment
alone suggests. The reference hashes the file's modification time - the tick count as a decimal
string - and then renders the sixteen bytes through .NET's GUID byte order, which reverses the
first three groups. So the probe does not assert a formula; it *inverts* one. It reads the
file's `Last-Modified` from the static delivery route, which is truncated to a whole second,
and searches the ten million sub-second tick values for the one whose hash is the `ETag` the
listing sent. A match proves the encoding, the byte order and the source of the timestamp
together, and prints the two plausible near-misses beside it.

Read-only: it lists items and reads two bytes of one file to learn its modification time.

Usage:
    python3 tools/probe_media_source.py http://your-jellyfin:8096 -u username
"""

from __future__ import annotations

import collections
import datetime
import email.utils
import hashlib
from typing import Any, Dict, List, Optional, Tuple

from _probe import Probe, ProbeError, Server, main

#: The item types that have a file behind them, and therefore a media source.
TYPES = ("Movie", "Episode", "Audio")

#: How many of each to look at. The field set is a property of the serialiser rather than of the
#: library, so a few dozen of each is already every shape the route can produce.
SAMPLE = 60

#: .NET counts 100-nanosecond ticks from 0001-01-01; the Unix epoch sits here.
TICKS_AT_UNIX_EPOCH = 621_355_968_000_000_000
TICKS_PER_SECOND = 10_000_000


def _guid_hex(digest: bytes) -> str:
    """Sixteen bytes as .NET renders a GUID with `ToString("N")`.

    The first three groups are little-endian integers and the last eight bytes are in order, so
    the string is *not* the digest's own hexadecimal - bytes 0-3, 4-5 and 6-7 come out reversed.
    """
    return (digest[3::-1] + digest[5:3:-1] + digest[7:5:-1] + digest[8:]).hex()


def _etag_of(ticks: int) -> str:
    """The candidate `ETag` for a modification time of `ticks`."""
    return _guid_hex(hashlib.md5(str(ticks).encode("utf-16-le")).digest())  # noqa: S324


def _sample(server: Server) -> Dict[str, List[Dict[str, Any]]]:
    found: Dict[str, List[Dict[str, Any]]] = {}
    for kind in TYPES:
        page = server.get_where(
            "/Items",
            {
                "userId": server.user_id,
                "recursive": "true",
                "includeItemTypes": kind,
                "fields": "MediaSources,Path",
                "limit": SAMPLE,
            },
        )
        found[kind] = page.get("Items") or []
    if not any(found.values()):
        raise ProbeError("no items with files were returned; is the library empty?")
    return found


def _field_census(items: List[Dict[str, Any]]) -> Tuple[List[str], collections.Counter, int]:
    """The key order of the first source, how often each key appears, and how many sources."""
    order: List[str] = []
    seen: collections.Counter = collections.Counter()
    total = 0
    for item in items:
        for source in item.get("MediaSources") or []:
            total += 1
            if not order:
                order = list(source)
            for key in source:
                seen[key] += 1
    return order, seen, total


def _last_modified(server: Server, item: Dict[str, Any], kind: str) -> Optional[datetime.datetime]:
    """The file's modification time to the second, from the static delivery route's header.

    Two bytes of the body, which is all that is needed to make the route answer with headers.
    """
    route = "Audio" if kind == "Audio" else "Videos"
    path = f"/{route}/{item['Id']}/stream?static=true&api_key={server.token}"
    _, headers, _ = server.get_streaming(path, max_bytes=2, extra_headers={"Range": "bytes=0-1"})
    stamp = headers.get("Last-Modified")
    if not stamp:
        return None
    parsed = email.utils.parsedate_to_datetime(stamp)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed.astimezone(datetime.timezone.utc)


def _crack(etag: str, second: datetime.datetime) -> Optional[int]:
    """The tick count in that second whose hash is `etag`, or nothing.

    Ten million candidates, one MD5 of a short string each: a second of work to prove a
    derivation that would otherwise be a reading of one line with two silent conventions in it.
    """
    epoch = datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)
    whole = int((second - epoch).total_seconds())
    base = TICKS_AT_UNIX_EPOCH + whole * TICKS_PER_SECOND
    for offset in range(TICKS_PER_SECOND):
        if _etag_of(base + offset) == etag:
            return base + offset
    return None


def run(server: Server) -> Probe:
    probe = Probe(
        script="probe_media_source.py",
        question="what does a media source carry on a listing, and how is its ETag derived?",
        document="specs/008-playback-negotiation-and-delivery/spec.md",
        section="section 3.1",
        expectation=(
            "every media source on a listing carries the same field set whatever the item type, "
            "with the transcoding fields and the default subtitle index absent; and the ETag is "
            "the MD5 of the file's modification time in ticks, rendered the way .NET renders a "
            "GUID rather than as the digest's own hexadecimal"
        ),
    )

    sampled = _sample(server)
    checks: List[bool] = []

    shapes: Dict[str, List[str]] = {}
    for kind, items in sampled.items():
        order, seen, total = _field_census(items)
        if not total:
            continue
        always = sorted(key for key, count in seen.items() if count == total)
        sometimes = sorted(key for key, count in seen.items() if count != total)
        shapes[kind] = always
        probe.observe(f"{kind} sources", f"{total}, {len(always)} field(s) on every one")
        probe.observe("  order", ", ".join(order))
        if sometimes:
            probe.observe("  not on all", ", ".join(f"{k} {seen[k]}/{total}" for k in sometimes))

    video_only = set(shapes.get("Movie", ())) - set(shapes.get("Audio", ()))
    probe.observe("video only", ", ".join(sorted(video_only)) or "(none)")
    checks.append(video_only == {"VideoType"})

    absent = {"TranscodingUrl", "TranscodingContainer", "DefaultSubtitleStreamIndex"}
    seen_absent = sorted(absent & set().union(*(set(one) for one in shapes.values())))
    probe.observe("never present", ", ".join(sorted(absent - set(seen_absent))) or "(none)")
    checks.append(not seen_absent)
    probe.note(
        "DefaultSubtitleStreamIndex is absent because this account's SubtitleMode is None, not "
        "because the route never sends it - the selection is per user and per remembered "
        "choice. TranscodingUrl and TranscodingContainer belong to a negotiation, which a "
        "listing is not."
    )

    cracked = 0
    attempted = 0
    for kind, items in sampled.items():
        item = next((one for one in items if (one.get("MediaSources") or [])), None)
        if item is None:
            continue
        source = item["MediaSources"][0]
        etag = source.get("ETag")
        if not etag:
            probe.observe(f"{kind} ETag", "absent")
            continue
        second = _last_modified(server, item, kind)
        if second is None:
            probe.observe(f"{kind} ETag", f"{etag}, no Last-Modified to search from")
            continue
        attempted += 1
        ticks = _crack(etag, second)
        if ticks is None:
            when = f"{second:%Y-%m-%dT%H:%M:%SZ}"
            probe.observe(f"{kind} ETag", f"{etag}, no tick in {when} hashes to it")
            continue
        cracked += 1
        digest = hashlib.md5(str(ticks).encode("utf-16-le")).digest()  # noqa: S324
        utf8 = hashlib.md5(str(ticks).encode("utf-8")).digest()  # noqa: S324
        probe.observe(f"{kind} ETag", f"{etag} == modification time {ticks} ticks")
        probe.observe("  digest hex", f"{digest.hex()}   (the same bytes, not GUID-ordered)")
        probe.observe("  if UTF-8", f"{_guid_hex(utf8)}   (the same ticks, hashed as UTF-8)")
    checks.append(attempted > 0 and cracked == attempted)

    probe.note(
        "The search is the point. Reading the assignment gives a formula with two silent "
        "conventions in it - the string is hashed as UTF-16 little-endian, and the sixteen "
        "bytes are rendered through .NET's GUID byte order, which reverses the first three "
        "groups. Either taken naively produces a well-formed 32-character tag that is wrong for "
        "every file, and no shape check would catch it. Recovering the exact tick count from "
        "the second the file was last written proves all three at once."
    )

    probe.conclude(
        "a media source on a listing carries one field set for audio and that set plus VideoType "
        "for video, with no transcoding fields; and its ETag is MD5 over the UTF-16 "
        "little-endian decimal string of the file's modification time in .NET ticks, rendered "
        "in .NET's GUID byte order - not the digest's own hexadecimal",
        matches_documentation=all(checks),
    )
    return probe


if __name__ == "__main__":
    raise SystemExit(main(run, "What does a media source carry, and how is its ETag derived?"))
