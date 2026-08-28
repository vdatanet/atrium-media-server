# SPDX-License-Identifier: GPL-3.0-or-later
"""Every 005 list route, asserted against its declared shape - AC-1 as a property.

The tasks gate added this roll-up for a reason it named: six tasks each asserted their own
route's shape and nothing asserted *every*, so an endpoint drifting later would have failed no
sweep. This walks the 005 surface itself - a list route added to `surface.yaml` without a row
here fails loudly - and holds spec section 3.1's four shapes: the three-field envelope
everywhere, the bare array of `/Items/Latest`, the filter summary, and the hint envelope.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from atrium.api.deps import require_user
from atrium.config.paths import DataPaths
from atrium.server import create_app
from tests.conformance.test_routes import surface_paths
from tests.conftest import data_dir
from tests.fixtures.query import QueryWorld, build_query_world

pytestmark = pytest.mark.conformance

ENVELOPE = {"Items", "TotalRecordCount", "StartIndex"}


def url_of(template: str, world: QueryWorld) -> tuple[str, dict[str, str]] | None:
    """A concrete request for each 005 route template, or None for the one non-list route."""
    first = world.series[0]
    table: dict[str, tuple[str, dict[str, str]] | None] = {
        "/Items": ("/Items", {"limit": "3"}),
        "/Items/{itemId}": None,  # one item, not a list - spec 3.2's second shape
        "/Items/Latest": ("/Items/Latest", {"limit": "3"}),
        "/Items/Filters": ("/Items/Filters", {}),
        "/Items/{itemId}/Similar": (f"/Items/{world.corpus[0]}/Similar", {}),
        "/Items/{itemId}/InstantMix": (f"/Items/{world.album}/InstantMix", {}),
        "/UserViews": ("/UserViews", {}),
        "/UserItems/Resume": ("/UserItems/Resume", {}),
        "/Shows/{seriesId}/Seasons": (f"/Shows/{first.id}/Seasons", {}),
        "/Shows/{seriesId}/Episodes": (f"/Shows/{first.id}/Episodes", {}),
        "/Shows/NextUp": ("/Shows/NextUp", {}),
        "/Artists": ("/Artists", {}),
        "/Artists/AlbumArtists": ("/Artists/AlbumArtists", {}),
        "/Genres": ("/Genres", {}),
        "/MusicGenres": ("/MusicGenres", {}),
        "/Years": ("/Years", {}),
        "/Search/Hints": ("/Search/Hints", {"searchTerm": "a"}),
    }
    assert template in table, (
        f"{template} is in surface.yaml under feature 005 and this roll-up has no row for it. "
        f"Add one with its declared shape, or AC-1 stops covering it."
    )
    return table[template]


def shape_of(body: Any) -> str:
    if isinstance(body, list):
        return "array"
    if not isinstance(body, dict):
        return "scalar"
    keys = set(body)
    if keys == ENVELOPE:
        return "envelope"
    if keys == {"Genres", "Tags", "OfficialRatings", "Years"}:
        return "filters"
    if keys == {"SearchHints", "TotalRecordCount"}:
        return "hints"
    return f"object({', '.join(sorted(keys))})"


EXPECTED = {
    "/Items/Latest": "array",
    "/Items/Filters": "filters",
    "/Search/Hints": "hints",
}


@pytest.fixture
def world_app(tmp_path: Path) -> Iterator[tuple[FastAPI, QueryWorld]]:
    paths: DataPaths = data_dir(tmp_path / "atrium")
    built = create_app(paths)
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


@pytest.mark.parametrize(
    "method,template", sorted(surface_paths(frozenset({"005"}))), ids=lambda one: str(one)
)
async def test_every_005_route_answers_its_declared_shape(
    client: httpx.AsyncClient,
    world_app: tuple[FastAPI, QueryWorld],
    method: str,
    template: str,
) -> None:
    assert method == "GET", "feature 005 is a read surface"
    target = url_of(template, world_app[1])
    if target is None:
        answered = await client.get(f"/Items/{world_app[1].corpus[0]}")
        assert answered.status_code == 200
        assert isinstance(answered.json(), dict)
        assert "Items" not in answered.json(), "the single-item route is not a list"
        return

    path, params = target
    answered = await client.get(path, params=params)
    assert answered.status_code == 200, f"{template}: {answered.text[:120]}"
    body = json.loads(answered.content)
    assert shape_of(body) == EXPECTED.get(template, "envelope"), template
