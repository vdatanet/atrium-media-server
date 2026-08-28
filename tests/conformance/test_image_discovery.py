# SPDX-License-Identifier: GPL-3.0-or-later
"""How a client finds an image before it fetches one - spec 006 section 3.1.

Nothing here serves a byte. A client reads `ImageTags` and its inherited neighbours off a 005
response and only then builds a URL, so this half of feature 006 lands on 005's surface: the
`ParentBackdropItemId` that 005 measured and emitted only half of, and the two criteria that are
statements about those maps rather than about the delivery route (AC-1, AC-14).

**The pairing is swept over every list route, not asserted on one.** An inherited tag with no
owning id is a tag a client cannot build a URL from, and the failure would be per route - the
lesson 005's own gate wrote into `test_shapes.py`: six tasks each asserted their own route and
nothing asserted *every*. The route table here is that file's, imported rather than copied, so a
route added to the surface without a row fails in one place.
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
from tests.conformance.test_shapes import url_of
from tests.conftest import data_dir
from tests.fixtures.query import (
    EPISODE_PRIMARY_TAG,
    SERIES_BACKDROP_TAGS,
    SERIES_PRIMARY_TAG,
    QueryWorld,
    build_query_world,
)

pytestmark = pytest.mark.conformance

#: The pair that is on the measured wire and stays off Atrium's, by Principle VI: no analysed
#: client reads it (006 spec section 3.1, 005 notes/item-shapes.md). Asserted absent so that a
#: later reader "completing" the inherited set has to argue with a test rather than with a
#: sentence.
DECLINED = ("ParentLogoItemId", "ParentLogoImageTag")


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


def rows_of(body: Any) -> list[dict[str, Any]]:
    """Every item-shaped row in a response, whichever of 005's four shapes it is."""
    if isinstance(body, list):
        return [row for row in body if isinstance(row, dict)]
    if not isinstance(body, dict):
        return []
    for key in ("Items", "SearchHints"):
        rows = body.get(key)
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    return []


# ------------------------------------------------------------------------------------------
# The pair
# ------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method,template", sorted(surface_paths(frozenset({"005"}))), ids=lambda one: str(one)
)
async def test_the_inherited_backdrop_id_and_tags_travel_together_on_every_row(
    client: httpx.AsyncClient,
    world_app: tuple[FastAPI, QueryWorld],
    method: str,
    template: str,
) -> None:
    """Present exactly together, on every row of every 005 response.

    Measured on the reference the same way and by the same rule: of 200 sampled episodes, 197
    carried both and **not one carried either alone**
    `[probe: manual requests via tools/_probe.py, Jellyfin 10.11.11, 2026-08-28]`.
    """
    assert method == "GET"
    world = world_app[1]
    target = url_of(template, world)
    if target is None:
        answered = await client.get(f"/Items/{world.series[0].episodes[0]}")
        rows = [answered.json()]
    else:
        path, params = target
        answered = await client.get(path, params=params)
        rows = rows_of(json.loads(answered.content))
    assert answered.status_code == 200, f"{template}: {answered.text[:120]}"

    for row in rows:
        has_id = "ParentBackdropItemId" in row
        has_tags = "ParentBackdropImageTags" in row
        assert has_id == has_tags, (
            f"{template}: {row.get('Type')} row {row.get('Id')} carries "
            f"{'the id without its tags' if has_id else 'tags with no owning id'}. A client "
            f"builds an image URL from the pair; half of it is unusable."
        )


async def test_the_named_backdrop_owner_is_the_item_whose_rows_produced_the_tags(
    client: httpx.AsyncClient, world_app: tuple[FastAPI, QueryWorld]
) -> None:
    """Not just present together - the same item. The id is only useful if it names the owner.

    Reproduces the reference's own answer: fetching each named owner and comparing its
    `BackdropImageTags` to the tags on the inheriting row agreed 12 of 12 times
    `[probe: manual requests via tools/_probe.py, Jellyfin 10.11.11, 2026-08-28]`.
    """
    world = world_app[1]
    answered = await client.get("/Items", params={"limit": "200", "recursive": "true"})
    rows = rows_of(json.loads(answered.content))
    checked = 0
    for row in rows:
        owner_id = row.get("ParentBackdropItemId")
        if owner_id is None:
            continue
        owner = json.loads((await client.get(f"/Items/{owner_id}")).content)
        assert owner["BackdropImageTags"] == row["ParentBackdropImageTags"], (
            f"{row['Type']} {row['Id']} inherits {row['ParentBackdropImageTags']} and names "
            f"{owner_id}, which carries {owner['BackdropImageTags']}"
        )
        checked += 1
    assert checked, (
        "no row in this world inherits a backdrop, so the assertion above ran zero times - the "
        "fixture stopped seeding the first series' backdrops"
    )
    assert world.series[0].id in {row.get("ParentBackdropItemId") for row in rows}


# ------------------------------------------------------------------------------------------
# The two criteria that are about the maps
# ------------------------------------------------------------------------------------------


async def test_ac1_a_poster_is_advertised_and_its_absence_is_an_empty_map(
    client: httpx.AsyncClient, world_app: tuple[FastAPI, QueryWorld]
) -> None:
    """AC-1: `ImageTags.Primary` where there is a poster, `{}` where there is none - never absent.

    The empty object is what lets a client tell "this item has no images" from "I did not ask for
    images" (spec section 3.1), and both halves are already in the world: the first film has a
    poster and the second has nothing.
    """
    world = world_app[1]
    with_poster = json.loads((await client.get(f"/Items/{world.corpus[0]}")).content)
    without = json.loads((await client.get(f"/Items/{world.corpus[1]}")).content)

    assert "Primary" in with_poster["ImageTags"]
    assert without["ImageTags"] == {}


async def test_ac14_an_episode_with_its_own_artwork_still_inherits_its_series(
    client: httpx.AsyncClient, world_app: tuple[FastAPI, QueryWorld]
) -> None:
    """AC-14: inheritance is unconditional, and this episode is the case that can prove it.

    It carries a `Primary` of its own under a series with a poster and two backdrops, so an
    emitter that only fell back when the child had nothing would answer differently here and
    identically everywhere else in this world. Falling back is the client's decision.

    Measured: every one of 200 sampled episodes carried a `Primary` of its own, and every one of
    them carried `SeriesPrimaryImageTag` and `SeriesId` as well
    `[probe: manual requests via tools/_probe.py, Jellyfin 10.11.11, 2026-08-28]`.
    """
    world = world_app[1]
    body = json.loads((await client.get(f"/Items/{world.imaged_episode}")).content)

    assert body["ImageTags"]["Primary"] == EPISODE_PRIMARY_TAG, "the precondition, not the claim"

    assert body["SeriesId"] == world.series[0].id
    assert body["SeriesPrimaryImageTag"] == SERIES_PRIMARY_TAG
    assert body["ParentBackdropItemId"] == world.series[0].id
    assert body["ParentBackdropImageTags"] == list(SERIES_BACKDROP_TAGS)


async def test_the_parent_logo_pair_stays_off_the_wire(
    client: httpx.AsyncClient, world_app: tuple[FastAPI, QueryWorld]
) -> None:
    """On the reference's wire, out of Atrium's by decision (Principle VI).

    `ParentBackdropItemId` arrived in this feature because a criterion needed it;
    `ParentLogoItemId` sits beside it in the same measured table and no analysed client reads it.
    This is the test that makes "we left it out" a decision somebody has to undo deliberately.
    """
    world = world_app[1]
    answered = await client.get("/Items", params={"limit": "200", "recursive": "true"})
    for row in rows_of(json.loads(answered.content)):
        for name in DECLINED:
            assert name not in row, f"{name} reached a {row.get('Type')} row"

    episode = json.loads((await client.get(f"/Items/{world.imaged_episode}")).content)
    for name in DECLINED:
        assert name not in episode
