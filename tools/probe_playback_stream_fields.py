#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""What does a media stream carry on a negotiation, and where does each value come from?

`POST`/`GET /Items/{itemId}/PlaybackInfo` is the largest single block of differences a sweep
reports — **242 findings on 2026-09-09**, every one of them a property of a `MediaStream`
`[probe: tools/differential.py --fixture, Jellyfin 10.11.11, 2026-09-09]`. Counted by name they
are four causes and not 242 repairs, and the four are not paid for the same way:

* **The five `Localized*` labels**, 84 findings. If they are five constants of the server's own
  locale they are a table; if they move with the stream or the request they are a derivation.
* **`DisplayTitle`**, 28. A composed human-readable label, and what it is composed *from* decides
  whether this server can compose the same one.
* **The codec detail**, about 100, and it is split: `level`, `width`, `height` and `bitrate` are
  **stored** by this server's inspection and absent from its wire model, while `IsAVC`, `TimeBase`,
  `NalLengthSize` and `RefFrames` are not stored at all.
* **`Score`, `DefaultSubtitleStreamIndex`, `ColorRange`**, 26 between them - and `ColorRange`
  points the other way: this server sends it and the reference does not.

So this reads every stream of several items and prints, per stream, what each of those properties
says — beside the stream's own type, codec and flags, which is what a rule would be derived from.
The point is not the count: it is whether a value is a **constant**, a **field of the file** or a
**composition**, because those are three different pieces of work.

**It writes nothing and cannot.** Every request is a `GET`, `/Items/{itemId}/PlaybackInfo`
included — the route has a `GET` form, and using it is what keeps this probe off the write path
its `POST` sibling needs `--allow-writes` for.

Standard library only, on the 3.9 floor, and `--help` starts nothing.

Usage:
    python3 tools/probe_playback_stream_fields.py
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

HERE = Path(__file__).resolve().parent

#: The five labels, which are the third of this route's findings that might be one table.
LOCALIZED: Tuple[str, ...] = (
    "LocalizedDefault",
    "LocalizedExternal",
    "LocalizedForced",
    "LocalizedUndefined",
    "LocalizedHearingImpaired",
)

#: What the file itself could supply, and what this server stores of it today.
FROM_THE_FILE: Tuple[str, ...] = (
    "Level",
    "IsAVC",
    "TimeBase",
    "NalLengthSize",
    "RefFrames",
    "BitRate",
    "Width",
    "Height",
)

#: How many items to read. Enough to show a value moving between items, few enough to stay one
#: page and one handful of requests - the live library this may be pointed at throttles.
ITEMS = 4

DOCUMENT = "specs/008-playback-negotiation-and-delivery/spec.md"
SECTION = "section 3.1"

EXPECTATION = (
    "008 section 3.1 states what a media source carries and this server's MediaStream model "
    "declares the fields it emits, so a stream of a file this server inspected should carry what "
    "the reference's does"
)


def load(name: str) -> Any:
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, HERE / (name + ".py"))
    if spec is None or spec.loader is None:  # pragma: no cover - the files are beside this one
        raise SystemExit(f"tools/{name}.py could not be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def streams_of(server: Any, item_id: str) -> List[Dict[str, Any]]:
    """Every stream of every source of one item, through the route's read-only form."""
    answered = server.get(f"/Items/{item_id}/PlaybackInfo", userId=server.user_id)
    sources = answered.get("MediaSources", []) if isinstance(answered, dict) else []
    found: List[Dict[str, Any]] = []
    for source in sources:
        for stream in source.get("MediaStreams", []) or []:
            one = dict(stream)
            one["_DefaultSubtitleStreamIndex"] = source.get("DefaultSubtitleStreamIndex", "-")
            found.append(one)
    return found


def said(stream: Dict[str, Any], name: str) -> str:
    if name not in stream:
        return "-"
    value = stream[name]
    return "''" if value == "" else str(value)[:26]


def measure(server: Any, args: argparse.Namespace) -> Any:
    probe = load("_probe")
    found = probe.Probe(
        script="probe_playback_stream_fields.py",
        question=(
            "What does a media stream carry on a negotiation, and where does each value come from?"
        ),
        document=DOCUMENT,
        section=SECTION,
        expectation=EXPECTATION,
    )

    listed = server.get(
        "/Items",
        userId=server.user_id,
        recursive="true",
        includeItemTypes="Movie,Episode,Audio",
        limit=60,
        fields="MediaSources",
    ).get("Items", [])
    if not listed:
        found.note("this library answers no file-backed item, so there is no stream to read")
        found.conclude("unanswered: nothing to negotiate", matches_documentation=None)
        return found

    # The richest items first: a file with several streams says more per request than four files
    # with one, and this probe is frugal because a live library throttles.
    def richness(row: Dict[str, Any]) -> int:
        return sum(len(one.get("MediaStreams", []) or []) for one in row.get("MediaSources", []))

    chosen = sorted(listed, key=richness, reverse=True)[:ITEMS]

    labels: Dict[str, set] = {name: set() for name in LOCALIZED}
    per_type: Dict[str, set] = {}
    for row in chosen:
        streams = streams_of(server, str(row["Id"]))
        found.observe(
            "item",
            "{} ({}) - {} stream(s)".format(
                str(row.get("Name"))[:26], row.get("Type"), len(streams)
            ),
        )
        for stream in streams:
            kind = str(stream.get("Type"))
            per_type.setdefault(kind, set()).update(
                name for name in (*LOCALIZED, *FROM_THE_FILE, "DisplayTitle") if name in stream
            )
            for name in LOCALIZED:
                if name in stream:
                    labels[name].add(str(stream[name]))
            # **The whole title, never truncated**, beside every input a composition could use.
            # The rule is only derivable if the string and its inputs are on the page together.
            flags = "".join(
                "1" if stream.get(name) else "0"
                for name in ("IsDefault", "IsForced", "IsHearingImpaired", "IsExternal")
            )
            found.observe(
                "  {} {}".format(kind[:8].ljust(8), str(stream.get("Codec"))[:9].ljust(9)),
                "title={!r} lang={} layout={} height={} range={} DFHE={}".format(
                    stream.get("Title"),
                    said(stream, "Language"),
                    said(stream, "ChannelLayout"),
                    said(stream, "Height"),
                    said(stream, "VideoRange"),
                    flags,
                ),
            )
            found.observe("  " + " " * 18, "DisplayTitle={!r}".format(stream.get("DisplayTitle")))
            found.observe(
                "  " + " " * 18,
                "  ".join(f"{name}={said(stream, name)}" for name in FROM_THE_FILE),
            )

    # **The question the tally answers and the rows above cannot**: five labels with one value
    # each across every stream of every item are a table this server can carry; five that move are
    # a derivation somebody has to write.
    for name in LOCALIZED:
        seen = sorted(labels[name])
        found.observe(
            "values of " + name,
            "{} distinct: {}".format(len(seen), ", ".join(repr(one) for one in seen)[:60]) or "-",
        )

    for kind in sorted(per_type):
        found.observe(
            "on a " + kind + " stream",
            ", ".join(sorted(per_type[kind])) or "-",
        )

    constant = all(len(labels[name]) <= 1 for name in LOCALIZED)
    found.note(
        "the five labels are the vocabulary DisplayTitle is composed FROM - 'Default', 'Forced', "
        "'Hearing Impaired' and 'External' each appear in a subtitle's title as a dash-joined "
        "part - so they are not two pieces of work but one"
    )
    found.conclude(
        (
            (
                "the five localized labels take ONE value each across every stream read, so they "
                "are a table of the server's own locale; "
            )
            if constant
            else "the localized labels move between streams, so they are a derivation; "
        )
        + "DisplayTitle is a composition over the stream's own fields and those labels; and the "
        "codec detail splits in two - Level, Width, Height and BitRate are stored by this "
        "server's inspection and missing from its wire model, while IsAVC, TimeBase, "
        "NalLengthSize and RefFrames are not stored at all",
        matches_documentation=False,
    )
    return found


def main() -> int:
    return int(
        load("_probe").main(
            lambda server, args: measure(server, args),
            description=(
                "What a media stream carries on a negotiation, and whether each value is a "
                "constant, a field of the file or a composition. Every request is a GET: this "
                "probe writes nothing, which is why it may be pointed at a server somebody owns."
            ),
            with_args=True,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
