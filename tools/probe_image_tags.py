#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Is a stale `tag` on an image URL an error, and what is the tag derived from?

Answers 006 OQ-1, OQ-2 and OQ-6. The verdict is OQ-2's, because it is the one with a claim to
contradict: specs/006 section 3.4 and AC-10 assume that a client asking for an image by a tag the
item no longer has receives the *current* image with a `200`, not a `404` - the client is behind,
not wrong. A reference that refuses instead makes AC-10 a deliberate divergence to record in
behaviours section 5, and this probe is what says so.

OQ-1 - how the tag is derived - is measured as far as read-only access allows: the tag's shape,
its stability across requests, and whether it reproduces as an MD5 of the image bytes themselves
(straight hex, and the .NET-Guid byte order the by-name ids use). A tag that does not reproduce
from the bytes is derived from something weaker - path and modification time are the usual
suspects - which OQ-1 already accepts: Atrium's requirement is only change-when-changed, and a
content hash satisfies it whatever the reference does.

OQ-6 - how chapters advertise their images - is read from the `Chapters` field of items that have
one, and confirmed by asking for `Images/Chapter/{index}` where an entry advertises a tag.

The same two responses that answer OQ-2 also carry section 3.4's cache headers - ETag,
Cache-Control with and without the tag, Last-Modified, Accept-Ranges - so those rows get measured
provenance for free, along with one conditional request: If-Modified-Since at the date the server
itself sent. An Age header, when present, is reported as what it is: evidence of a caching
intermediary, which scopes every header-level finding to the deployment measured.

What this probe cannot see, and says so: whether the tag *changes when the image file changes*.
That needs a write to the library and a rescan, which is the owner's disk, not a probe's. And a
library whose items carry no chapters leaves OQ-6 unexercised; the probe reports the sample it
actually had rather than guessing.

Writes: nothing.

Usage:
    python3 tools/probe_image_tags.py http://your-jellyfin:8096 -u username
"""

from __future__ import annotations

import hashlib
from typing import Any, Optional

from _probe import Probe, ProbeError, Server, main

#: How many items to page through looking for images and chapters. A bound, not the library:
#: the probe reports what it sampled.
PAGE = 200

#: How many primary-image items feed the derivation sample. Enough to tell a rule from a
#: coincidence; small enough to stay polite to someone else's server.
DERIVATION_SAMPLE = 12

HEX = set("0123456789abcdef")


def dotnet_guid(digest: bytes) -> str:
    """`new Guid(byte[16]).ToString("N")`: first three fields little-endian, the rest in order."""
    swapped = [
        digest[3],
        digest[2],
        digest[1],
        digest[0],
        digest[5],
        digest[4],
        digest[7],
        digest[6],
    ]
    return bytes(swapped).hex() + digest[8:16].hex()


def primary_items(server: Server) -> list[dict[str, Any]]:
    """Items carrying a Primary tag, from one bounded page."""
    page = server.get(
        "/Items",
        userId=server.user_id,
        Recursive="true",
        Limit=str(PAGE),
        ImageTypeLimit="1",
        EnableImageTypes="Primary",
    )
    return [
        item
        for item in (page or {}).get("Items") or []
        if (item.get("ImageTags") or {}).get("Primary")
    ]


def chapter_items(server: Server) -> list[dict[str, Any]]:
    """Movies and episodes whose `Chapters` field is non-empty, from one bounded page."""
    page = server.get(
        "/Items",
        userId=server.user_id,
        Recursive="true",
        IncludeItemTypes="Movie,Episode",
        Fields="Chapters",
        Limit=str(PAGE),
    )
    return [item for item in (page or {}).get("Items") or [] if item.get("Chapters")]


def is_tag_shaped(tag: str) -> bool:
    return len(tag) == 32 and set(tag.lower()) <= HEX


def run(server: Server) -> Probe:
    probe = Probe(
        script="probe_image_tags.py",
        question="is a stale image `tag` an error, and what is the tag derived from?",
        document="specs/006-images/spec.md",
        section="section 3.4 and AC-10 (OQ-1, OQ-2, OQ-6)",
        expectation=("a request carrying a stale tag answers 200 with the current image, not 404"),
    )

    items = primary_items(server)
    if not items:
        raise ProbeError("no item on this server carries a Primary image; nothing can be measured")
    probe.observe("items with a Primary tag", f"{len(items)} in a page of {PAGE}")

    # The containers' own shapes - 006 spec section 3.1's example: a map for ImageTags, a list
    # for BackdropImageTags. Observed here so the example's citation is re-runnable. The page
    # above cannot answer the backdrop half: it asks with EnableImageTypes=Primary, which prunes
    # BackdropImageTags out of its own response - so the backdrop question gets an unpruned page.
    maps = sum(1 for item in items if isinstance(item.get("ImageTags"), dict))
    probe.observe("ImageTags is a map", f"{maps} of {len(items)}")
    unpruned = (
        server.get(
            "/Items",
            userId=server.user_id,
            IncludeItemTypes="Movie,Series",
            Recursive="true",
            Limit="24",
        )
        or {}
    ).get("Items") or []
    with_backdrops = [item for item in unpruned if item.get("BackdropImageTags")]
    lists = sum(1 for item in with_backdrops if isinstance(item["BackdropImageTags"], list))
    probe.observe(
        "BackdropImageTags is a list",
        f"{lists} of {len(with_backdrops)} carrying one, in an unpruned page of {len(unpruned)}",
    )

    # -- OQ-1: what the tag is derived from, as far as read-only access can tell ------------

    shaped = 0
    md5_hex = 0
    md5_guid = 0
    stable = 0
    etag_equal = 0
    etag_contains = 0
    sample = items[:DERIVATION_SAMPLE]
    for item in sample:
        tag = item["ImageTags"]["Primary"]
        if is_tag_shaped(tag):
            shaped += 1

        status, headers, payload = server.get_raw(f"/Items/{item['Id']}/Images/Primary")
        if status != 200:
            probe.note(f"GET Images/Primary for {item['Id']} answered {status}; skipped")
            continue
        digest = hashlib.md5(payload).digest()  # noqa: S324 - the reference's tags are MD5-sized
        if digest.hex() == tag.lower():
            md5_hex += 1
        if dotnet_guid(digest) == tag.lower():
            md5_guid += 1

        etag = (headers.get("ETag") or "").strip('"')
        if etag == tag:
            etag_equal += 1
        elif tag in etag:
            etag_contains += 1

        again = server.get(f"/Items/{item['Id']}", userId=server.user_id)
        if (again.get("ImageTags") or {}).get("Primary") == tag:
            stable += 1

    probe.observe("tags shaped as 32 hex", f"{shaped} of {len(sample)}")
    probe.observe("tag == MD5(image bytes)", f"{md5_hex} of {len(sample)}")
    probe.observe("tag == Guid(MD5(image bytes))", f"{md5_guid} of {len(sample)}")
    probe.observe("tag unchanged on re-request", f"{stable} of {len(sample)}")
    probe.observe("ETag equals the tag", f"{etag_equal} of {len(sample)}")
    probe.observe("ETag contains the tag", f"{etag_contains} of {len(sample)}")
    if md5_hex == 0 and md5_guid == 0:
        probe.note(
            "OQ-1: the tag does not reproduce from the image bytes in either spelling, so it is "
            "derived from something other than content - path and modification time are the "
            "usual suspects, and read-only access cannot tell which. OQ-1 already accepts this: "
            "Atrium's requirement is change-when-changed, and a content hash is at least as good."
        )

    # -- OQ-2: the stale tag, which is the verdict -------------------------------------------

    first = items[0]
    item_id, tag = first["Id"], first["ImageTags"]["Primary"]
    _, bare_headers, current = server.get_raw(f"/Items/{item_id}/Images/Primary")
    stale = ("0" if tag[0] != "0" else "1") + tag[1:]

    status_real, tagged_headers, body_real = server.get_raw(
        f"/Items/{item_id}/Images/Primary", tag=tag
    )
    status_stale, _, body_stale = server.get_raw(f"/Items/{item_id}/Images/Primary", tag=stale)
    probe.observe("current tag on the URL", f"{status_real}, {len(body_real)}B")
    probe.observe("stale tag on the URL", f"{status_stale}, {len(body_stale)}B")
    same_bytes = body_stale == current
    if status_stale == 200:
        probe.observe("stale answer is the current image", "yes" if same_bytes else "NO")

    # -- section 3.4's headers, on the same two responses ------------------------------------

    for name in ("ETag", "Cache-Control", "Last-Modified", "Accept-Ranges", "Age", "Vary"):
        bare, tagged = bare_headers.get(name), tagged_headers.get(name)
        value = bare if bare == tagged else f"{bare}  /  {tagged} with the tag"
        probe.observe(f"header {name}", value)
    if not bare_headers.get("ETag"):
        probe.note(
            "no ETag was observed on an image response - Last-Modified carries the conditional "
            "contract here, and an image etag would be an Atrium addition rather than a "
            "reproduction, which is what section 3.4's table records."
        )
    if bare_headers.get("Age"):
        probe.note(
            "an Age header means a caching intermediary sits between this probe and the "
            "reference, so header-level findings describe the deployment measured, not "
            "necessarily the bare server."
        )

    last_modified = bare_headers.get("Last-Modified")
    if last_modified:
        # The private spelling because a conditional GET needs its own request header, which
        # `get_raw` has no way to carry.
        status_ims, _, body_ims = server._request(
            "GET",
            f"/Items/{item_id}/Images/Primary",
            extra_headers={"If-Modified-Since": last_modified},
            raw=True,
        )
        probe.observe("If-Modified-Since, current date", f"{status_ims}, {len(body_ims)}B")

    # -- OQ-6: how chapters advertise their images -------------------------------------------

    with_chapters = chapter_items(server)
    probe.observe("items with chapters", f"{len(with_chapters)} in a page of {PAGE}")
    if with_chapters:
        keys: set = set()
        tagged_entries = 0
        total_entries = 0
        tagged_item: Optional[str] = None
        tagged_index: Optional[int] = None
        for item in with_chapters:
            for index, entry in enumerate(item["Chapters"]):
                total_entries += 1
                keys |= set(entry)
                if entry.get("ImageTag"):
                    tagged_entries += 1
                    if tagged_item is None:
                        tagged_item, tagged_index = item["Id"], index
        probe.observe("chapter entry keys", ", ".join(sorted(keys)))
        probe.observe("entries advertising ImageTag", f"{tagged_entries} of {total_entries}")

        if tagged_item is not None:
            status, headers, payload = server.get_raw(
                f"/Items/{tagged_item}/Images/Chapter/{tagged_index}"
            )
            probe.observe(
                f"GET Images/Chapter/{tagged_index} (advertised)",
                f"{status}, {headers.get('Content-Type', 'none')}, {len(payload)}B",
            )
        else:
            item_id = with_chapters[0]["Id"]
            status, _, payload = server.get_raw(f"/Items/{item_id}/Images/Chapter/0")
            probe.observe("GET Images/Chapter/0 (none advertised)", f"{status}, {len(payload)}B")
            probe.note(
                "OQ-6: chapters exist but none advertises an ImageTag on this server - chapter "
                "image extraction may be disabled or unfinished, so the shape of an advertised "
                "chapter image stays unexercised here."
            )
    else:
        probe.note(
            "OQ-6: no sampled movie or episode carries chapters at all, so how they advertise "
            "images was not exercised; the question needs a library with chaptered video."
        )

    # -- verdict -----------------------------------------------------------------------------

    if status_stale == 200 and same_bytes:
        probe.conclude(
            "a stale tag is not an error: the reference answers 200 with the current image, "
            "byte-identical to a request carrying no tag",
            matches_documentation=True,
        )
    elif status_stale == 200:
        probe.conclude(
            "a stale tag answers 200 but with bytes that differ from the current image - "
            "something varies with the tag parameter, which section 3.4 does not describe",
            matches_documentation=False,
        )
    else:
        probe.conclude(
            f"a stale tag answers {status_stale}, not 200 with the current image - AC-10 is a "
            "divergence to argue in behaviours section 5, not a reproduction",
            matches_documentation=False,
        )
    return probe


if __name__ == "__main__":
    raise SystemExit(main(run, __doc__.splitlines()[0]))
