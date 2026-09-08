#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""What does an untagged track's row carry that this server's does not, and where does it come from?

Four properties of 005 §3.2's audio tranche were still missing when the sweep of 2026-09-08 ran,
and they are four different questions wearing one name
`[probe: tools/differential.py --fixture, Jellyfin 10.11.11, 2026-09-08]`:

* **`HasLyrics`**, on 24 rows. [005's list](../specs/005-item-query-api/tasks.md) already owns it
  and calls it *"lyric discovery, which is a feature and not a field"* — the reference answers
  `false` bare and `true` beside an `.lrc`. What this probe adds is whether that is still what a
  reference answers, and on which rows.
* **`PremiereDate`**, on 20 rows, and every observed value was `0001-01-01T00:00:00.0000000Z` —
  .NET's zero date. Nothing in this repository records it. A zero date is not a value, so whether
  it reaches the wire on *every* audio row or only some decides whether it is a field to fill or
  a divergence to argue.
* **`AlbumArtist`**, on 6 rows, and this is the third of
  [005 cause #10](../specs/005-item-query-api/tasks.md) — the other two, `ProductionYear` and
  `RunTimeTicks`, were closed on 2026-09-08. This server derives an artist **container** from the
  directories and no **credit**, so `item_artists` holds 4 rows for 12 tracks on a scanned
  fixture: only the two whose files carry real tags.
* **`AlbumPrimaryImageTag`**, on 4 rows. 005 §3.2 already declares it for `Audio`, and the
  emitter reads the album's own primary image — so this is artwork the album does not have here.

So this reads every `Audio` and every `MusicAlbum` row of a library, at the **default list width**
and nothing wider, and prints per row what each of the four says, beside the path the row came
from. What decides each property is then readable rather than inferred from a positional report
whose rows do not line up.

**It writes nothing and cannot.** Every request is a `GET`, which is why it may be pointed at a
server somebody owns.

Standard library only, on the 3.9 floor, and `--help` starts nothing.

Usage:
    python3 tools/probe_music_row_tranche.py
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

HERE = Path(__file__).resolve().parent

#: The four, in the order the sweep counts them.
TRANCHE: Tuple[str, ...] = ("HasLyrics", "PremiereDate", "AlbumArtist", "AlbumPrimaryImageTag")

#: How many rows to read. The fixture holds a dozen tracks and a real library holds thousands;
#: this is a shape question, and a page is enough to answer it.
PAGE = 40

DOCUMENT = "specs/005-item-query-api/spec.md"
SECTION = "section 3.2"

EXPECTATION = (
    "005 section 3.2 declares Album, AlbumId and AlbumPrimaryImageTag for an Audio row and "
    "AlbumArtist for an Audio and a MusicAlbum row, and this server emits all four - so a track "
    "whose album artist the directories name should carry it, as the reference's does"
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


def rows_of(server: Any, item_type: str) -> List[Dict[str, Any]]:
    answered = server.get(
        "/Items",
        userId=server.user_id,
        recursive="true",
        includeItemTypes=item_type,
        limit=PAGE,
        sortBy="SortName",
    )
    return [dict(one) for one in answered.get("Items", [])]


def said(row: Dict[str, Any], name: str) -> str:
    """What one row says about one property: the value, or that the property is not there."""
    if name not in row:
        return "-"
    value = row[name]
    if value is None:
        return "null"
    return str(value)[:34]


def tally(rows: List[Dict[str, Any]], name: str) -> str:
    """How many rows carry the property at all, and how many distinct values they carry."""
    carried = [row[name] for row in rows if name in row]
    distinct = {str(one) for one in carried}
    if not carried:
        return f"on 0 of {len(rows)}"
    return "on {} of {}, {} distinct value(s): {}".format(
        len(carried), len(rows), len(distinct), ", ".join(sorted(distinct)[:3])[:60]
    )


def measure(server: Any, args: argparse.Namespace) -> Any:
    probe = load("_probe")
    found = probe.Probe(
        script="probe_music_row_tranche.py",
        question="What does a track's list row carry of 005's audio tranche, and what decides it?",
        document=DOCUMENT,
        section=SECTION,
        expectation=EXPECTATION,
    )

    tracks = rows_of(server, "Audio")
    albums = rows_of(server, "MusicAlbum")
    if not tracks:
        found.note("this library answers no Audio row, so the question has no subject")
        found.conclude("unanswered: no track to read", matches_documentation=None)
        return found

    for name in TRANCHE:
        found.observe("Audio rows: " + name, tally(tracks, name))
    found.observe("MusicAlbum rows: AlbumArtist", tally(albums, "AlbumArtist"))

    # **Per row, because a tally cannot say what decides a property.** A track whose file carries
    # tags and one named only by its directories are different cases, and on this fixture they sit
    # in different libraries.
    for row in tracks[:12]:
        found.observe(
            "  " + str(row.get("Name"))[:24],
            "  ".join(f"{name}={said(row, name)}" for name in TRANCHE),
        )

    # A track's own credits beside the album artist, since the sweep reported all four artist
    # properties as length differences on the same rows.
    for row in tracks[:6]:
        found.observe(
            "  credits of " + str(row.get("Name"))[:18],
            "Artists={}  AlbumArtists={}".format(
                row.get("Artists", "(absent)"), row.get("AlbumArtists", "(absent)")
            ),
        )

    zero_dates = [
        row for row in tracks if str(row.get("PremiereDate", "")).startswith("0001-01-01")
    ]
    if zero_dates:
        found.note(
            f"{len(zero_dates)} of {len(tracks)} PremiereDate values are .NET's zero date, "
            "which is not a date anybody wrote"
        )

    held = all(name in tracks[0] for name in ("AlbumArtist",))
    found.conclude(
        "a track's row carries "
        + ", ".join(name for name in TRANCHE if name in tracks[0])
        + " and not "
        + (", ".join(name for name in TRANCHE if name not in tracks[0]) or "-"),
        matches_documentation=held,
    )
    return found


def main() -> int:
    return int(
        load("_probe").main(
            lambda server, args: measure(server, args),
            description=(
                "What a track's list row carries of 005 section 3.2's audio tranche, and what "
                "decides each. Every request is a GET: this probe writes nothing, which is why "
                "it may be pointed at a server somebody owns."
            ),
            with_args=True,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
