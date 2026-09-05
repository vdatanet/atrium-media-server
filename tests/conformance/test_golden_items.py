# SPDX-License-Identifier: GPL-3.0-or-later
"""The item bodies, byte for byte, one per type and route.

Spec section 6 puts `GET /Items` and `GET /Items/{itemId}` at L3, and until the differential
harness (010) exists these goldens are the L3 debt's down payment (plan section 8): a reviewed
byte-exact body per item type, for the list row and the full body, over the seeded world.

**No placeholders.** The world is deterministic by construction - fixed identifiers, fixed dates,
a pinned server identity - and the `Etag` is a hash of exactly those, so every byte here is
stable. A golden that needed a mask would be reporting fixture entropy, and the fixture's own
tests forbid it (`test_query_fixture.test_two_builds_derive_the_same_world`).

**Reviewed, not just recorded**: each file is a statement about what a client's decoder receives
- field order included, which is the reference document's order by construction of the models.

**Checked against something external**: the anchor is `tests/golden/reference-item-shapes.txt` -
the reference's own per-type property presence, captured `[probe: tools/probe_item_shapes.py,
Jellyfin 10.11.11, 2026-08-28]`. Without it these files' only non-Atrium anchor was the review
itself, which is a golden regenerated from the server under test wearing a second hat (the
2026-08-28 audit's M47). Values stay Atrium's own - the fixture world and the reference library
share no items - but every property a golden carries or omits is checked against that table by
`test_the_property_set_per_type_is_the_references`, below.

**The check is executed, not read.** Until the 2026-09-04 audit's L16 it was neither: the table
was cited in this docstring and `grep -rn reference-item-shapes tests/ tools/` found no reader, so
the only assertion that ran over these sixteen files compared Atrium against its own
`--update-golden` output. A review happens once, at the diff a person looked at; a regeneration
that adds or drops a property afterwards is a diff nobody is obliged to look at, and that is the
gap an anchor read only by eye cannot close.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from atrium.api.deps import require_user
from atrium.config.paths import DataPaths
from atrium.domain.items import ItemType
from atrium.library.identity import for_by_name
from atrium.server import create_app
from tests.conformance.golden import assert_golden
from tests.conformance.test_golden import STATE
from tests.fixtures.query import QueryWorld, build_query_world

pytestmark = pytest.mark.conformance

GOLDENS = Path(__file__).resolve().parents[1] / "golden"

#: The reference capture: the probe's per-type table, plus the per-type summary under it.
ANCHOR = GOLDENS / "reference-item-shapes.txt"

#: The eight types these goldens cover, and the seven the capture has a column for. `Genre` is a
#: **by-name** row and the probe sampled none: its library has no `/Items?includeItemTypes=Genre`
#: reading in it, so there is nothing here to hold a by-name golden against. Asserted below rather
#: than assumed, so a regenerated capture that grows the column starts failing until it is used.
GOLDEN_TYPES = (
    "Movie",
    "Series",
    "Season",
    "Episode",
    "MusicArtist",
    "MusicAlbum",
    "Audio",
    "Genre",
)
CAPTURED_TYPES = GOLDEN_TYPES[:-1]

#: Properties an Atrium golden carries that the capture does not account for: the type and the
#: property, then the widths it is on and the argument for it. **Every one of these is a property
#: the reference was not observed sending on that type**, which the capture's own header says is
#: not the same as one it never sends: `-` there means absent from every sampled body, and a null
#: property is absent everywhere (behaviours section 1.7). They are listed rather than excused, and
#: the widths are part of the record - a season row carries no rollup and only its full body does.
#: The check below asserts this set **exactly**, per width, so an entry that goes away reddens as
#: loudly as a third that arrives.
UNACCOUNTED: dict[tuple[str, str], tuple[tuple[str, ...], str]] = {
    ("Episode", "SeriesThumbImageTag"): (
        ("Row", "Full"),
        "005 section 3.2 carries it as `Episode` - unconfirmed: the probe saw it neither bare nor "
        "asked for nor in a full body across twelve episodes, and whether it is gated or simply "
        "absent because none of those episodes' series carries a Thumb cannot be told apart from "
        "outside. It stays in the table, and here, rather than being deleted on one library's "
        "evidence.",
    ),
    ("Season", "CumulativeRunTimeTicks"): (
        ("Full",),
        "The capture's full-body summary lists it as an unasked addition on Series, MusicArtist, "
        "MusicAlbum and Playlist and not on Season, so what is unobserved is the season rollup "
        "rather than the property. Atrium sums it wherever the children carry runtimes, which is "
        "what 007's fixture change made reachable at all (007 tasks, T4's note: it was absent "
        "from every golden in the repository until then, for want of a child with a runtime).",
    ),
}


@pytest.fixture
def golden_paths(tmp_path: Path) -> DataPaths:
    paths = DataPaths(tmp_path / "atrium")
    paths.prepare()
    paths.state_file.write_text(json.dumps(STATE, indent=1), encoding="utf-8")
    return paths


@pytest.fixture
def world_app(golden_paths: DataPaths) -> Iterator[tuple[FastAPI, QueryWorld]]:
    built = create_app(golden_paths)
    built.state.readiness.mark_ready()
    with built.state.sessions.begin() as opened:
        world = build_query_world(opened)
    built.dependency_overrides[require_user] = lambda: world.everyone
    yield built, world
    built.dependency_overrides.clear()
    built.state.db.dispose()


@pytest.fixture
async def client(world_app: tuple[FastAPI, QueryWorld]) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=world_app[0])
    async with httpx.AsyncClient(transport=transport, base_url="http://atrium:8096") as opened:
        yield opened


def chosen(world: QueryWorld) -> dict[str, str]:
    """One item per type: the ones the fixture gives the most attachments."""
    first = world.series[0]
    return {
        "Movie": world.corpus[0],
        "Series": first.id,
        "Season": first.seasons[0],
        "Episode": first.episodes[0],
        "MusicArtist": world.album_artist,
        "MusicAlbum": world.album,
        "Audio": world.tracks[0],
        "Genre": for_by_name(ItemType.GENRE, "sci-fi"),
    }


@pytest.mark.parametrize("type_name", GOLDEN_TYPES)
async def test_the_list_row_per_type(
    client: httpx.AsyncClient,
    world_app: tuple[FastAPI, QueryWorld],
    type_name: str,
    pytestconfig: pytest.Config,
) -> None:
    item_id = chosen(world_app[1])[type_name]
    answered = await client.get("/Items", params={"ids": item_id})
    assert answered.status_code == 200
    assert_golden(f"Items.Row.{type_name}", answered, config=pytestconfig)


@pytest.mark.parametrize("type_name", GOLDEN_TYPES)
async def test_the_full_body_per_type(
    client: httpx.AsyncClient,
    world_app: tuple[FastAPI, QueryWorld],
    type_name: str,
    pytestconfig: pytest.Config,
) -> None:
    item_id = chosen(world_app[1])[type_name]
    answered = await client.get(f"/Items/{item_id}")
    assert answered.status_code == 200
    assert_golden(f"Items.Full.{type_name}", answered, config=pytestconfig)


# ------------------------------------------------------------------------------------------
# The anchor, read
# ------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ReferenceShape:
    """What the reference was observed emitting for one type, per width.

    Two sets rather than one, because the capture measured two widths and they are not one
    representation: a bare `/Items/{itemId}` carries up to thirty-nine properties a bare list row
    does not, with no `Fields` asked - which is the finding that rewrote 005 section 3.2.
    """

    row: frozenset[str]
    full: frozenset[str]

    #: The counts the capture's own summary states for this type, which is what holds the parse.
    stated_row: int
    stated_full: int


#: `  property   tier   Movie  Series ...`, then one line per property, then a blank line.
_HEADER = re.compile(r"^\s+property\s+tier\s+(.+)$")

#: `  Movie   12 sampled; bare list row 21 properties, bare /Items/{itemId} 56; the full route
#: adds unasked A, B, C; list-only D`
_SUMMARY = re.compile(
    r"^\s{2}(\w+)\s+\d+ sampled; bare list row (\d+) properties, "
    r"bare /Items/\{itemId\} (\d+)(?P<rest>.*)$"
)


def _named(text: str) -> set[str]:
    return {one.strip() for one in text.split(",") if one.strip()}


def reference_shapes() -> dict[str, ReferenceShape]:
    """`tests/golden/reference-item-shapes.txt`, parsed into a set of properties per type.

    **The parse is held by the file's own arithmetic** rather than trusted: the capture states a
    property count per type and per width beside every summary line, and this asserts the sets it
    built have exactly those sizes. A capture this cannot read is therefore a failure and not an
    empty comparison, which is the difference between a check and a check-shaped hole - and a
    regenerated file is exactly where that hole would open.
    """
    lines = ANCHOR.read_text(encoding="utf-8").splitlines()
    start = next(index for index, line in enumerate(lines) if _HEADER.match(line))
    columns = _HEADER.match(lines[start]).group(1).split()  # type: ignore[union-attr]

    presence: dict[str, dict[str, str]] = {}
    for line in lines[start + 2 :]:
        cells = line.split()
        if len(cells) != len(columns) + 2:
            break
        name, _tier, *values = cells
        presence[name] = dict(zip(columns, values, strict=True))

    shapes: dict[str, ReferenceShape] = {}
    for line in lines:
        summary = _SUMMARY.match(line)
        if summary is None:
            continue
        type_name, stated_row, stated_full = summary.group(1), *summary.group(2, 3)
        rest = summary.group("rest")
        adds = re.search(r"the full route adds unasked ([^;]+)", rest)
        only = re.search(r"list-only (.+)$", rest)
        row = frozenset(name for name, seen in presence.items() if seen.get(type_name, "-") != "-")
        shapes[type_name] = ReferenceShape(
            row=row,
            full=(row | _named(adds.group(1) if adds else ""))
            - _named(only.group(1) if only else ""),
            stated_row=int(stated_row),
            stated_full=int(stated_full),
        )
    return shapes


def always_present(shapes: dict[str, ReferenceShape]) -> frozenset[str]:
    """The properties the capture found on **every** type it sampled.

    Derived from the columns rather than read from the capture's own `tier` label, which is why
    that column is discarded above: the tier is the probe's word for what its own numbers say, and
    a check that took it on trust would be checking the label. A golden missing one of these is
    missing a property the reference sends to every client for every item.
    """
    return frozenset.intersection(*(shape.row for shape in shapes.values()))


def golden_properties(name: str) -> set[str]:
    """One golden's top-level property names - the row unwrapped from its envelope."""
    body = json.loads((GOLDENS / f"{name}.json").read_text(encoding="utf-8"))
    return set(body["Items"][0] if name.startswith("Items.Row.") else body)


#: `/UserViews` is the capture's **third shape** and the one type in it reached through a route of
#: its own rather than through `/Items`. Its summary counts one property more than its column
#: holds, at both widths - so a property those six bodies carried is named in no row of the table,
#: and which one cannot be recovered from the file. Excluded from the arithmetic below with that
#: said out loud; no golden here is a view row, so nothing this module checks rests on it.
CAPTURE_UNRECONCILED = frozenset({"UserViews"})


def test_the_reference_capture_parses_to_the_counts_it_states() -> None:
    """The guard on the guard: a capture that stopped parsing must fail here, not pass quietly.

    Both widths, over every `/Items` type the capture holds - including `Playlist` and `Folder`,
    which these goldens have no file for, because a parse that broke only outside the tested seven
    is still a broken parse.
    """
    shapes = reference_shapes()
    assert set(shapes) >= set(CAPTURED_TYPES), sorted(shapes)
    reconciled = set(shapes) - CAPTURE_UNRECONCILED
    assert reconciled >= set(CAPTURED_TYPES) | {"Playlist", "Folder"}, sorted(reconciled)
    for type_name in sorted(reconciled):
        shape = shapes[type_name]
        assert len(shape.row) == shape.stated_row, f"{type_name}: list row"
        assert len(shape.full) == shape.stated_full, f"{type_name}: full body"
    assert len(always_present(shapes)) == 12


def test_the_by_name_golden_is_outside_the_capture_and_says_so() -> None:
    """`Genre` is the one golden type the anchor cannot speak for, asserted rather than skipped.

    The probe sampled ten types and no by-name row is among them, so a `Genre` golden has nothing
    external to be held against - the same L3 debt these files are the down payment on, one type
    wider. If a regenerated capture grows the column, this fails and the type joins the check.
    """
    assert set(GOLDEN_TYPES) - set(CAPTURED_TYPES) == {"Genre"}
    assert "Genre" not in reference_shapes()


@pytest.mark.parametrize("type_name", CAPTURED_TYPES)
@pytest.mark.parametrize("width", ["Row", "Full"])
def test_the_property_set_per_type_is_the_references(type_name: str, width: str) -> None:
    """Every property a golden carries or omits, against the capture - L16's assertion.

    Two claims, and the second is the one a review cannot keep across regenerations:

    * every property the reference sends on **every** type is in this golden;
    * every property this golden carries is one the reference was observed sending on this type
      and at this width, or is one of the two `UNACCOUNTED` entries with its argument.

    What is deliberately **not** asserted is the converse of the second - that Atrium sends
    everything the reference does. That is a real gap and it has an owner: behaviours section 3's
    *"item fields outside the observed union omitted"* row carries the remaining tranche with the
    differential's key-set pass behind it, measured against a live server rather than against a
    table. A golden cannot make that claim, because a property absent here may be absent from the
    fixture rather than from the emitter.
    """
    shapes = reference_shapes()
    observed = shapes[type_name].row if width == "Row" else shapes[type_name].full
    carried = golden_properties(f"Items.{width}.{type_name}")

    assert always_present(shapes) <= carried, (
        f"Items.{width}.{type_name} omits "
        f"{sorted(always_present(shapes) - carried)}, which the reference sends on every type"
    )
    unaccounted = {
        name
        for (typed, name), (widths, _why) in UNACCOUNTED.items()
        if typed == type_name and width in widths
    }
    assert carried - observed == unaccounted, (
        f"Items.{width}.{type_name} carries {sorted(carried - observed - unaccounted)}, which the "
        f"capture records the reference not sending on a {type_name}. Either the reference does "
        f"send it and the capture needs regenerating, or this is a property Atrium invents - and "
        f"a property nobody asked for is one no client reads."
    )
