#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Which properties does the reference emit per item type, bare and when asked?

Answers 005 spec section 3.2 and the registry plan section 6.5 turns it into. Section 3.2 sorts
roughly seventy properties into three tiers - always present, present when the type has them, and
only when asked for through `Fields` - and it assembled them from what two clients *read*, not
from a measurement of what the reference *sends*. T9 copies that table into code, so a wrong row
is a field silently absent, or silently present, on every response of an item type.

The confound this probe exists to survive: **the reference omits nulls**
(behaviours section 1.7), so a property missing from one item's body may be gated, or may simply
be null on that item. One sample cannot tell those apart. This probe therefore samples up to
SAMPLE items per type and reports presence as a count - `12/12` is a property the type always
carries, `3/12` is one it sometimes has, and both are different from the `0/12` that means gated.

Four bodies per type: a list row bare and one with **every member of the server's own
`ItemFields` enum** asked for, and the same item from `/Items/{itemId}` both ways. Asking for the
whole vocabulary rather than the nineteen names section 3.2 happens to list is what makes "gated"
a measurement instead of a restatement of the claim. The list and the full route are measured
separately because section 3.2 claims one representation for both, and nothing had checked it.

It also records every property whose value arrives as an explicit `null`, because behaviours
section 1.7 says none can: that entry rests on a source citation, and a source citation says what
the code appears to do.

A type the live library cannot produce is reported as **unmeasured**, never guessed.

Writes: nothing.

Usage:
    python3 tools/probe_item_shapes.py http://your-jellyfin:8096 -u username
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Optional

from _probe import Probe, ProbeError, Server, main

#: How many items of a type to sample. Enough that a property present on every one of them is
#: unlikely to be a coincidence of the library, small enough to stay one request.
SAMPLE = 12

#: The gated tokens spec section 3.2 lists under "Only when asked for via `Fields`".
GATED_CLAIM = [
    "MediaSources",
    "MediaStreams",
    "Path",
    "Etag",
    "Chapters",
    "DateCreated",
    "DateLastMediaAdded",
    "ProviderIds",
    "Tags",
    "Taglines",
    "ExternalUrls",
    "OriginalTitle",
    "ParentId",
    "CumulativeRunTimeTicks",
    "RecursiveItemCount",
    "ChildCount",
    "SortName",
    "Width",
    "Height",
]

#: Spec section 3.2's "Present when the item type has them" Common group. Six of these are
#: `ItemFields` tokens, which is the question this list exists to settle: a token is gated by
#: definition, so a name in both lists is in the wrong one.
COMMON_CLAIM = [
    "SortName",
    "Overview",
    "ProductionYear",
    "PremiereDate",
    "RunTimeTicks",
    "OfficialRating",
    "CommunityRating",
    "Genres",
    "GenreItems",
    "Studios",
    "People",
    "PrimaryImageAspectRatio",
]

#: The always-present claim of spec section 3.2, expanded from its first table.
ALWAYS_CLAIM = [
    "Id",
    "ServerId",
    "Name",
    "Type",
    "MediaType",
    "IsFolder",
    "UserData",
    "ImageTags",
    "BackdropImageTags",
]

#: Label -> the `IncludeItemTypes` token that reaches one through `/Items`. `None` means the type
#: has no `/Items` query that answers and is fetched by the route named in `measure`.
TYPES: list[tuple[str, Optional[str]]] = [
    ("Movie", "Movie"),
    ("Series", "Series"),
    ("Season", "Season"),
    ("Episode", "Episode"),
    ("MusicArtist", "MusicArtist"),
    ("MusicAlbum", "MusicAlbum"),
    ("Audio", "Audio"),
    ("Playlist", "Playlist"),
    ("Folder", "Folder"),
    ("UserViews", None),
]

SPEC_PATH = "/api-docs/openapi.json"


# ------------------------------------------------------------------------------------------------
# Fetching
# ------------------------------------------------------------------------------------------------


def list_rows(
    server: Server, item_type: str, fields: Optional[str], ids: Optional[list[str]] = None
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "UserId": server.user_id,
        "Recursive": "true",
        "Limit": SAMPLE,
        "SortBy": "SortName",
    }
    if ids is None:
        params["IncludeItemTypes"] = item_type
    else:
        params["Ids"] = ",".join(ids)
    if fields:
        params["Fields"] = fields
    result = server.get_where("/Items", params)
    return list(result.get("Items", []))


def user_view_rows(server: Server, fields: Optional[str]) -> list[dict[str, Any]]:
    """`/UserViews` is the only route that answers with the library roots.

    `/Items?IncludeItemTypes=CollectionFolder` returns zero rows on the reference, so a finding
    about these rows is a finding about *this route*, not about the type in isolation.
    """
    params: dict[str, Any] = {"userId": server.user_id}
    if fields:
        params["fields"] = fields
    result = server.get_where("/UserViews", params)
    return list(result.get("Items", []))


def artist_rows(server: Server, fields: Optional[str]) -> list[dict[str, Any]]:
    """MusicArtist has a by-name route of its own, which is how clients reach artists.

    `/Items?IncludeItemTypes=MusicArtist` can answer nothing on a library whose artists exist only
    as by-name rows, so the fallback is not cosmetic.
    """
    params: dict[str, Any] = {"UserId": server.user_id, "Limit": SAMPLE}
    if fields:
        params["Fields"] = fields
    result = server.get_where("/Artists", params)
    return list(result.get("Items", []))


def full_body(server: Server, item_id: str, fields: Optional[str]) -> Optional[dict[str, Any]]:
    params: dict[str, Any] = {"userId": server.user_id}
    if fields:
        params["fields"] = fields
    try:
        body = server.get_where(f"/Items/{item_id}", params)
    except ProbeError:
        return None
    return body if isinstance(body, dict) else None


def item_fields_enum(server: Server) -> Optional[set[str]]:
    """The `ItemFields` enum from the server's own OpenAPI document, if it is reachable.

    It is both the ask-list and a check on spec section 3.2's `[spec: ItemFields]` citation: a
    name in its gated list that is not a member is a token the server drops silently
    (behaviours section 1.12), so nothing else would ever say so.
    """
    url = server.base + SPEC_PATH
    try:
        # S310: operator-supplied URL, the same one every other request here uses.
        with urllib.request.urlopen(url, timeout=server.timeout) as response:  # noqa: S310
            document = json.loads(response.read())
    except (urllib.error.URLError, ValueError, OSError):
        return None
    schema = document.get("components", {}).get("schemas", {}).get("ItemFields", {})
    values = schema.get("enum")
    if not isinstance(values, list):
        return None
    return {str(value) for value in values}


# ------------------------------------------------------------------------------------------------
# Counting
# ------------------------------------------------------------------------------------------------


class Presence:
    """Per-property presence counts for one item type, across the four bodies fetched for it."""

    def __init__(self, type_name: str) -> None:
        self.type_name = type_name
        self.sampled = 0
        self.bare: dict[str, int] = {}
        self.asked: dict[str, int] = {}
        self.full_bare: set[str] = set()
        self.full_asked: set[str] = set()
        self.full_reached = False
        self.user_data_keys: set[str] = set()
        self.saw_empty_image_tags = False
        self.explicit_nulls: dict[str, int] = {}
        self.reported_types: set[str] = set()

    def count(self, rows: list[dict[str, Any]], into: dict[str, int]) -> None:
        for row in rows:
            for name, value in row.items():
                into[name] = into.get(name, 0) + 1
                if value is None:
                    self.explicit_nulls[name] = self.explicit_nulls.get(name, 0) + 1
            reported = row.get("Type")
            if isinstance(reported, str):
                self.reported_types.add(reported)
            user_data = row.get("UserData")
            if isinstance(user_data, dict):
                self.user_data_keys.update(user_data)
            tags = row.get("ImageTags")
            if isinstance(tags, dict) and not tags:
                self.saw_empty_image_tags = True

    def bare_ratio(self, name: str) -> str:
        return f"{self.bare.get(name, 0)}/{self.sampled}"


def measure(server: Server, type_name: str, query: Optional[str], gated: str) -> Presence:
    presence = Presence(type_name)

    if type_name == "UserViews":
        bare = user_view_rows(server, None)
        asked = user_view_rows(server, gated) if bare else []
    elif type_name == "MusicArtist":
        bare = list_rows(server, query or type_name, None)
        if bare:
            asked = list_rows(server, "", gated, [r["Id"] for r in bare])
        else:
            bare = artist_rows(server, None)
            asked = artist_rows(server, gated) if bare else []
    else:
        bare = list_rows(server, query or type_name, None)
        asked = list_rows(server, "", gated, [r["Id"] for r in bare]) if bare else []

    if not bare:
        return presence

    presence.sampled = len(bare)
    presence.count(bare, presence.bare)
    presence.count(asked, presence.asked)

    first = full_body(server, bare[0]["Id"], None)
    if first is not None:
        presence.full_reached = True
        presence.full_bare = set(first)
        second = full_body(server, bare[0]["Id"], gated)
        presence.full_asked = set(second) if second else set()
    return presence


# ------------------------------------------------------------------------------------------------
# Classifying
# ------------------------------------------------------------------------------------------------


def classify(measured: list[Presence]) -> dict[str, str]:
    """Sort every observed property into the tier the measurement puts it in.

    always    present bare on every sampled item of every measured type
    per-type  present bare somewhere, but not on every item of every type
    gated     never present bare anywhere, and present once asked for
    """
    tiers: dict[str, str] = {}
    names: set[str] = set()
    for presence in measured:
        names.update(presence.bare)
        names.update(presence.asked)

    for name in names:
        anywhere = any(presence.bare.get(name, 0) for presence in measured)
        everywhere = all(presence.bare.get(name, 0) == presence.sampled for presence in measured)
        if everywhere:
            tiers[name] = "always"
        elif anywhere:
            tiers[name] = "per-type"
        else:
            tiers[name] = "gated"
    return tiers


def print_matrix(measured: list[Presence], tiers: dict[str, str]) -> None:
    order = {"always": 0, "per-type": 1, "gated": 2}
    names = sorted(tiers, key=lambda n: (order[tiers[n]], n))
    width = max(len(n) for n in names)

    print()
    print("  bare presence per type, as present/sampled. `-` is absent from every sampled body.")
    print()
    header = "  " + "property".ljust(width) + "  tier      "
    header += "  ".join(p.type_name[:11].rjust(11) for p in measured)
    print(header)
    print("  " + "-" * (len(header) - 2))
    for name in names:
        cells = []
        for presence in measured:
            count = presence.bare.get(name, 0)
            cells.append(("-" if not count else presence.bare_ratio(name)).rjust(11))
        print("  " + name.ljust(width) + "  " + tiers[name].ljust(10) + "  ".join(cells))
    print()


# ------------------------------------------------------------------------------------------------
# The probe
# ------------------------------------------------------------------------------------------------


def run(server: Server) -> Probe:
    probe = Probe(
        script="probe_item_shapes.py",
        question="which properties does the reference emit per item type, bare and when asked?",
        document="specs/005-item-query-api/spec.md",
        section="section 3.2 (and plan section 6.5)",
        expectation=(
            "one representation for both routes: nine properties always present, a per-type "
            "group, and nineteen names emitted only when requested through `Fields`"
        ),
    )
    contradictions: list[str] = []

    enum = item_fields_enum(server)
    if enum is None:
        ask = sorted(set(GATED_CLAIM) | set(COMMON_CLAIM))
        probe.note(
            f"the ItemFields enum could not be read from {SPEC_PATH}. The ask-list falls back to "
            "the names spec section 3.2 lists, so `gated` here means `not emitted bare and "
            "emitted when one of those is asked for` - a weaker statement than the enum allows."
        )
    else:
        ask = sorted(enum)
        strangers = [n for n in GATED_CLAIM if n not in enum]
        tail = ": " + ", ".join(strangers) if strangers else ""
        probe.observe(
            "ItemFields enum",
            f"{len(enum)} members, all asked for; {len(strangers)} of spec 3.2's gated names "
            f"are not members{tail}",
        )
        if strangers:
            contradictions.append(
                "not ItemFields tokens, so requesting them does nothing: " + ", ".join(strangers)
            )

    gated = ",".join(ask)
    measured: list[Presence] = []
    unmeasured: list[str] = []

    for type_name, query in TYPES:
        presence = measure(server, type_name, query, gated)
        if presence.sampled:
            measured.append(presence)
        else:
            unmeasured.append(type_name)

    if not measured:
        raise ProbeError("the library produced no items of any measured type")

    # The tiers are a claim about `/Items`. `/UserViews` is a different route with a shape of
    # its own, and folding it in would let one fat row promote a gated name to "per-type" for
    # every content type - which is exactly what the first run of this probe did.
    content = [p for p in measured if p.type_name != "UserViews"]
    views = next((p for p in measured if p.type_name == "UserViews"), None)
    if not content:
        raise ProbeError("no content type was reachable through /Items")

    tiers = classify(content)
    print_matrix(measured, tiers)

    # -- tier 1: the always-present claim ------------------------------------------------------
    for name in ALWAYS_CLAIM:
        tier = tiers.get(name)
        if tier == "always":
            continue
        if tier is None:
            contradictions.append(f"{name} claimed always-present, never observed")
            continue
        missing = ", ".join(
            f"{p.type_name} {p.bare_ratio(name)}"
            for p in content
            if p.bare.get(name, 0) != p.sampled
        )
        contradictions.append(f"{name} claimed always-present, measured {tier}: {missing}")

    surplus = [n for n, t in sorted(tiers.items()) if t == "always" and n not in ALWAYS_CLAIM]
    if surplus:
        contradictions.append(
            "always-present on every content type but absent from the claim: " + ", ".join(surplus)
        )

    # -- tier 2: the Common group --------------------------------------------------------------
    common_gated = [n for n in COMMON_CLAIM if tiers.get(n) == "gated"]
    if common_gated:
        contradictions.append(
            "claimed present when the type has them, but emitted only when asked for: "
            + ", ".join(common_gated)
        )
    common_absent = [n for n in COMMON_CLAIM if n not in tiers]
    if common_absent:
        contradictions.append(
            "claimed present when the type has them, never observed at all: "
            + ", ".join(common_absent)
        )

    # -- tier 3: the gated claim ---------------------------------------------------------------
    for name in GATED_CLAIM:
        if tiers.get(name) not in ("always", "per-type"):
            continue
        where = ", ".join(
            f"{p.type_name} {p.bare_ratio(name)}" for p in content if p.bare.get(name, 0)
        )
        contradictions.append(f"{name} claimed gated, present without asking on {where}")

    never = [
        n for n in GATED_CLAIM if n not in tiers and not any(n in p.full_asked for p in content)
    ]
    if never:
        contradictions.append(
            "claimed gated, never appeared even when asked for: " + ", ".join(never)
        )

    # -- one representation, or two? -----------------------------------------------------------
    widest = 0
    widest_type = ""
    for presence in measured:
        if not presence.full_reached:
            probe.observe(presence.type_name, "no /Items/{itemId} body; list only")
            continue
        only_full = sorted(presence.full_bare - set(presence.bare))
        only_list = sorted(set(presence.bare) - presence.full_bare)
        detail = f"{presence.sampled} sampled; bare list row {len(presence.bare)} properties, "
        detail += f"bare /Items/{{itemId}} {len(presence.full_bare)}"
        if only_full:
            detail += "; the full route adds unasked " + ", ".join(only_full)
        if only_list:
            detail += "; list-only " + ", ".join(only_list)
        if not only_full and not only_list:
            detail += "; the same properties both ways"
        probe.observe(presence.type_name, detail)
        if len(only_full) > widest:
            widest, widest_type = len(only_full), presence.type_name
    if widest:
        contradictions.append(
            f"the two routes are not one representation: bare /Items/{{itemId}} carries up to "
            f"{widest} properties a bare list row does not ({widest_type}), with no `Fields` asked"
        )

    # -- behaviours 1.7: a null property is absent, everywhere ---------------------------------
    nulls: dict[str, int] = {}
    for presence in measured:
        for name, count in presence.explicit_nulls.items():
            nulls[name] = nulls.get(name, 0) + count
    if nulls:
        listed = ", ".join(f"{n} x{c}" for n, c in sorted(nulls.items()))
        probe.observe("explicit nulls", listed)
        contradictions.append(
            "behaviours 1.7 says a null property is absent everywhere; these arrived as an "
            "explicit null: " + listed
        )
    else:
        probe.observe("explicit nulls", "none - behaviours 1.7 holds across every body fetched")

    # -- UserData, ImageTags, PrimaryImageAspectRatio ------------------------------------------
    user_data_keys: set[str] = set()
    for presence in measured:
        user_data_keys.update(presence.user_data_keys)
    probe.observe("UserData keys", ", ".join(sorted(user_data_keys)) or "none observed")
    for required in ("Key", "ItemId"):
        if required not in user_data_keys:
            contradictions.append(
                f"behaviours 2.1 claims UserData carries {required}; not observed"
            )

    empty_seen = [p.type_name for p in measured if p.saw_empty_image_tags]
    probe.observe(
        "ImageTags when empty",
        "`{}` on " + ", ".join(empty_seen) if empty_seen else "no imageless item sampled",
    )

    aspect = tiers.get("PrimaryImageAspectRatio")
    probe.observe(
        "PrimaryImageAspectRatio", f"unasked tier: {aspect}" if aspect else "never emitted"
    )

    if views is not None:
        unasked = sorted({n for n in GATED_CLAIM + COMMON_CLAIM if views.bare.get(n, 0)})
        probe.observe(
            "UserViews rows report Type",
            ", ".join(sorted(views.reported_types)) or "no Type at all",
        )
        probe.observe(
            "UserViews shape",
            f"{len(views.bare)} properties unasked, including "
            + (", ".join(unasked) or "nothing section 3.2 gates"),
        )
        if unasked:
            contradictions.append(
                "/UserViews is a third shape: it carries unasked "
                + ", ".join(unasked)
                + " - names section 3.2 gates or calls per-type on /Items"
            )

    if unmeasured:
        probe.observe("unmeasured types", ", ".join(unmeasured) + " - the library produced none")
        probe.note(
            "an unmeasured type is not a finding about that type. Its row in spec section 3.2 "
            "stays as it was, resting on nothing this probe saw."
        )

    if contradictions:
        probe.conclude("; ".join(contradictions), matches_documentation=False)
    else:
        probe.conclude(
            f"all three tiers hold as spec section 3.2 states them, across {len(measured)} "
            "measured types",
            matches_documentation=True,
        )
    return probe


if __name__ == "__main__":
    raise SystemExit(main(run, __doc__.splitlines()[0]))
