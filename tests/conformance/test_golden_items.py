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

**Reviewed against something external**: the review's anchor is
`tests/golden/reference-item-shapes.txt` - the reference's own per-type property presence,
captured `[probe: tools/probe_item_shapes.py, Jellyfin 10.11.11, 2026-08-28]`. Without it these
files' only non-Atrium anchor was the review itself, which is a golden regenerated from the
server under test wearing a second hat (the 2026-08-28 audit's M47). Values stay Atrium's own -
the fixture world and the reference library share no items - but every property a golden carries
or omits is checkable against that table.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator
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


@pytest.mark.parametrize(
    "type_name",
    ["Movie", "Series", "Season", "Episode", "MusicArtist", "MusicAlbum", "Audio", "Genre"],
)
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


@pytest.mark.parametrize(
    "type_name",
    ["Movie", "Series", "Season", "Episode", "MusicArtist", "MusicAlbum", "Audio", "Genre"],
)
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
