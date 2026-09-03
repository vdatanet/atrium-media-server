# SPDX-License-Identifier: GPL-3.0-or-later
"""The eight properties the two wide widths carry, and the one width that must not gain them.

005 T1 measured that there is **no single item representation**: a bare `GET /Items/{itemId}`
carries up to 39 properties a bare list row does not, and `/UserViews` is a third width. So a
field the reference sends on a full body is not evidence about a list row, and the repair for a
missing one is not "emit it everywhere" - that trades one difference for another.

**Where these eight came from.** 010's first complete conformance sweep, against a single-use
reference instance over this repository's own fixture, joined **1:1 by `(Type, Name)`** rather
than by list position: a listing ordered by a key the two servers disagree about is a listing
whose rows do not line up, and the same sweep's positional readings had reported `Album`,
`IndexNumber`, `ParentIndexNumber`, `Artists`, `ArtistItems` and `AlbumArtists` as properties
Atrium sends and the reference does not - every one of which disappears under the join. What
survived it was present on **every** reference full body and **every** `/UserViews` row, and on
**no** joined list row `[probe: tools/differential.py --fixture, Jellyfin 10.11.11, 2026-09-03]`.

This file is the guard for that shape. Delete a name from `WIDE_ONLY` and a full body loses it
here; move one into `ALWAYS` or `PER_TYPE` and a list row gains it here.
"""

from __future__ import annotations

import ast
import json
from collections.abc import AsyncIterator, Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from atrium.api.deps import require_user
from atrium.api.item_dto import WIDE_ONLY
from atrium.config.paths import DataPaths
from atrium.server import create_app
from atrium.users.policy import CONTENT_DOWNLOADING
from tests.conformance.test_golden import STATE
from tests.fixtures.query import QueryWorld, build_query_world

pytestmark = pytest.mark.conformance

#: The directory whose `BuildContext(...)` constructions the structural guard walks.
API_PACKAGE = Path(__file__).resolve().parents[2] / "src" / "atrium" / "api"

#: What the reference answered on every joined full body and every view row, for an account
#: permitted everything, over a **file-backed** item.
ON_A_FILE: dict[str, Any] = {
    "CanDownload": True,
    "EnableMediaSourceDisplay": True,
    "LocalTrailerCount": 0,
    "LockData": False,
    "LockedFields": [],
    "PlayAccess": "Full",
    "RemoteTrailers": [],
    "SpecialFeatureCount": 0,
}


@pytest.fixture
def wide_paths(tmp_path: Path) -> DataPaths:
    paths = DataPaths(tmp_path / "atrium")
    paths.prepare()
    paths.state_file.write_text(json.dumps(STATE, indent=1), encoding="utf-8")
    return paths


@pytest.fixture
def world_app(wide_paths: DataPaths) -> Iterator[tuple[FastAPI, QueryWorld]]:
    built = create_app(wide_paths)
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


def test_the_wide_only_tier_is_what_was_measured() -> None:
    """The registry constant and the measurement are one table, spelled once."""
    assert set(WIDE_ONLY) == set(ON_A_FILE)


async def test_a_full_body_carries_all_eight(
    client: httpx.AsyncClient, world_app: tuple[FastAPI, QueryWorld]
) -> None:
    _app, world = world_app
    answered = await client.get(f"/Items/{world.corpus[0]}")
    assert answered.status_code == 200, answered.text
    body = dict(answered.json())
    for name, value in ON_A_FILE.items():
        assert name in body, f"{name} is absent from a full body"
        assert body[name] == value, f"{name} is {body[name]!r}, not {value!r}"


async def test_a_bare_list_row_carries_none_of_them(
    client: httpx.AsyncClient, world_app: tuple[FastAPI, QueryWorld]
) -> None:
    """The half that keeps the repair inside its width, and the one this file exists for."""
    answered = await client.get("/Items", params={"recursive": "true", "limit": 100})
    assert answered.status_code == 200, answered.text
    rows = list(answered.json()["Items"])
    assert rows, "no rows to check"
    offending = sorted({name for row in rows for name in ON_A_FILE if name in row})
    assert not offending, f"a bare list row carries a full-body property: {offending}"


async def test_a_user_view_row_carries_all_eight(
    client: httpx.AsyncClient, world_app: tuple[FastAPI, QueryWorld]
) -> None:
    answered = await client.get("/UserViews")
    assert answered.status_code == 200, answered.text
    rows = list(answered.json()["Items"])
    assert rows, "no views to check"
    for row in rows:
        for name in ON_A_FILE:
            assert name in row, f"{name} is absent from the {row['Name']!r} view row"


async def test_a_folder_is_not_downloadable_however_permissive_the_account(
    client: httpx.AsyncClient, world_app: tuple[FastAPI, QueryWorld]
) -> None:
    """Measured on the reference: a library root answers `false` to an administrator whose policy
    permits downloading, where a film beneath it answers `true`."""
    views = list((await client.get("/UserViews")).json()["Items"])
    assert views and all(view["CanDownload"] is False for view in views)

    _app, world = world_app
    film = dict((await client.get(f"/Items/{world.corpus[0]}")).json())
    assert film["CanDownload"] is True


async def test_the_two_permissions_follow_the_effective_account(
    client: httpx.AsyncClient, world_app: tuple[FastAPI, QueryWorld]
) -> None:
    """`PlayAccess` is `EnableMediaPlayback` and `CanDownload` is `EnableContentDownloading`,
    both measured on a reference seat with each denied in turn."""
    app, world = world_app
    denied = replace(
        world.everyone,
        enable_media_playback=False,
        policy_extra={**world.everyone.policy_extra, CONTENT_DOWNLOADING: False},
    )
    app.dependency_overrides[require_user] = lambda: denied

    body = dict((await client.get(f"/Items/{world.corpus[0]}")).json())
    assert body["PlayAccess"] == "None"
    assert body["CanDownload"] is False


async def test_an_episode_names_its_season(
    client: httpx.AsyncClient, world_app: tuple[FastAPI, QueryWorld]
) -> None:
    """`SeasonName` is a per-type property of **both** widths - measured on every joined episode
    row and every joined episode body - so it is asserted on both."""
    _app, world = world_app
    episode = world.series[0].episodes[0]
    body = dict((await client.get(f"/Items/{episode}")).json())
    season = dict((await client.get(f"/Items/{body['SeasonId']}")).json())
    assert body["SeasonName"] == season["Name"]

    listed = await client.get(
        "/Items", params={"recursive": "true", "includeItemTypes": "Episode", "limit": 100}
    )
    rows = [row for row in listed.json()["Items"] if row["Id"] == episode]
    assert rows and rows[0]["SeasonName"] == season["Name"]


# ------------------------------------------------------------------------------------------
# The structural half: every context filler names the access it emits under
# ------------------------------------------------------------------------------------------


def _build_context_calls() -> list[tuple[str, int, frozenset[str]]]:
    found: list[tuple[str, int, frozenset[str]]] = []
    for module in sorted(API_PACKAGE.glob("*.py")):
        tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "BuildContext"
            ):
                found.append(
                    (
                        module.name,
                        node.lineno,
                        frozenset(
                            keyword.arg for keyword in node.keywords if keyword.arg is not None
                        ),
                    )
                )
    return found


def test_every_item_building_route_names_the_access_it_emits_under() -> None:
    """`CanDownload` and `PlayAccess` are the **effective** user's, so a route that forgot to say
    whose would answer somebody else's - the failure `BuildContext.policy` already has a guard
    for, one field along. Read from the source, so adding a route cannot quietly skip it."""
    calls = _build_context_calls()
    assert len(calls) >= 13, f"only {len(calls)} BuildContext constructions found - parser broken?"
    missing = [(name, line) for name, line, keywords in calls if "access" not in keywords]
    assert not missing, f"these BuildContext constructions name no access: {missing}"


def test_the_context_refuses_to_be_built_without_an_access() -> None:
    """The absence of a default is the mechanism, so it is asserted rather than assumed."""
    from atrium.api.item_dto import BuildContext
    from atrium.media.decision import EVERY_PERMISSION

    with pytest.raises(TypeError):
        BuildContext(server_id="s" * 32, policy=EVERY_PERMISSION)  # type: ignore[call-arg]
