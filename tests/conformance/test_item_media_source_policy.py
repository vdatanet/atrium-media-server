# SPDX-License-Identifier: GPL-3.0-or-later
"""A listed `MediaSources` carries the reading account's playback permissions, on every route.

The reference builds an item body's media sources and a profile-less negotiation's from one
function `[source: Emby.Server.Implementations/Dto/DtoService.cs:261,
Emby.Server.Implementations/Library/MediaSourceManager.cs:355-372 @ v10.11.11]`, so a listing
answers the same **one permission per media kind** a `PlaybackInfo` carrying no profile does:
a video item's `SupportsTranscoding` is `EnableVideoPlaybackTranscoding` and its
`SupportsDirectStream` is `EnablePlaybackRemuxing`; an audio item's `SupportsTranscoding` is
`EnableAudioPlaybackTranscoding` and its `SupportsDirectStream` is untouched;
`SupportsDirectPlay` is untouched on both. Measured against the single-use reference instance
over this repository's own fixture, across the six policy shapes, on `GET /Items/{itemId}`,
`GET /Items` and `GET /Items/Latest`, and on a video item, an audio item and a video item nothing
had ever inspected
`[probe: tools/probe_playback_info.py, Jellyfin 10.11.11, 2026-09-02]`.

**Why this file asks every route rather than the one the shortfall was noticed on.** The gap this
closes was recorded in behaviours section 5 with its own warning: the policy reaches
`api/item_dto.py`'s `BuildContext`, *"which is a shared context and not one route"*. A fix proven
on `GET /Items` alone is a fix that silently is not applied on the other eight. The list below is
not remembered: `test_every_item_building_route_fills_the_policy` enumerates the fifteen
`BuildContext(...)` constructions in `src/atrium/api/` from the source itself and fails on one
that does not name `policy`, which is what covers the six whose answer carries no `MediaSources`
at all - the by-name envelope, `/Shows/{seriesId}/Seasons`, `/UserViews`, `/Sessions` (which omits
the property outright) and the two user-data writers.

Delete `policy=policy_of(target)` from any route below and that route's rows fail here.
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
from sqlalchemy import delete

from atrium.api.deps import require_user
from atrium.config.paths import DataPaths
from atrium.db import models
from atrium.db.repositories import UserRepository
from atrium.domain.user import User
from atrium.server import create_app
from atrium.users.policy import AUDIO_TRANSCODING, REMUXING, VIDEO_TRANSCODING
from tests.conformance.test_golden import STATE
from tests.fixtures.query import QueryWorld, build_query_world

pytestmark = pytest.mark.conformance

#: The directory whose `BuildContext(...)` constructions the structural guard walks.
API_PACKAGE = Path(__file__).resolve().parents[2] / "src" / "atrium" / "api"

#: `(SupportsDirectPlay, SupportsDirectStream, SupportsTranscoding)` - the wire's own order.
Flags = tuple[bool, bool, bool]

#: The six policy shapes, each with what a **video** source and an **audio** source answer.
#: `EnableMediaPlayback` is in the table because it is the one permission that reads like it
#: belongs here and does not: no route consults it (behaviours section 2.21), and the reference
#: answers a seat with it denied exactly as a permitted one.
SHAPES: list[tuple[str, dict[str, Any], Flags, Flags]] = [
    ("every permission granted", {}, (True, True, True), (True, True, True)),
    (
        "video transcoding denied alone",
        {VIDEO_TRANSCODING: False},
        (True, True, False),
        (True, True, True),
    ),
    (
        "audio transcoding denied alone",
        {AUDIO_TRANSCODING: False},
        (True, True, True),
        (True, True, False),
    ),
    ("remuxing denied alone", {REMUXING: False}, (True, False, True), (True, True, True)),
    (
        "all three denied",
        {VIDEO_TRANSCODING: False, AUDIO_TRANSCODING: False, REMUXING: False},
        (True, False, False),
        (True, True, False),
    ),
    (
        "media playback denied",
        {"EnableMediaPlayback": False},
        (True, True, True),
        (True, True, True),
    ),
]

#: The types whose sources follow the video rule. The audio rule is `Audio`'s; nothing else in v1
#: carries a media source at all.
VIDEO_ROWS = frozenset({"Movie", "Episode"})


@pytest.fixture
def policy_paths(tmp_path: Path) -> DataPaths:
    paths = DataPaths(tmp_path / "atrium")
    paths.prepare()
    paths.state_file.write_text(json.dumps(STATE, indent=1), encoding="utf-8")
    return paths


@pytest.fixture
def world_app(policy_paths: DataPaths) -> Iterator[tuple[FastAPI, QueryWorld]]:
    built = create_app(policy_paths)
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


def as_user(app: FastAPI, person: User, policy: dict[str, Any]) -> None:
    """Sign the next requests in as this account with these permissions denied or granted."""
    seat = replace(person, policy_extra={**person.policy_extra, **policy})
    app.dependency_overrides[require_user] = lambda: seat


def flags(source: dict[str, Any]) -> Flags:
    return (
        source["SupportsDirectPlay"],
        source["SupportsDirectStream"],
        source["SupportsTranscoding"],
    )


def rows_with_sources(body: Any) -> list[dict[str, Any]]:
    """Every row of an answer that carries at least one media source, envelope or bare array."""
    rows = body["Items"] if isinstance(body, dict) else body
    return [one for one in rows if one.get("MediaSources")]


async def sourced(client: httpx.AsyncClient, path: str, **params: Any) -> list[dict[str, Any]]:
    answered = await client.get(path, params={"fields": "MediaSources", **params})
    assert answered.status_code == 200, answered.text
    found = rows_with_sources(answered.json())
    assert found, f"{path} answered no row carrying MediaSources, so it can prove nothing"
    return found


def assert_rows(rows: list[dict[str, Any]], video: Flags, audio: Flags) -> None:
    """Every source of every row, against the rule for that row's own media kind."""
    for row in rows:
        expected = video if row["Type"] in VIDEO_ROWS else audio
        for source in row["MediaSources"]:
            assert flags(source) == expected, f"{row['Type']} {row['Name']!r}"


# ------------------------------------------------------------------------------------------
# One route per test, so a route that stops filling the context is named by the failure
# ------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "policy,video,audio", [row[1:] for row in SHAPES], ids=[row[0] for row in SHAPES]
)
async def test_the_full_body_carries_the_accounts_flags(
    client: httpx.AsyncClient,
    world_app: tuple[FastAPI, QueryWorld],
    policy: dict[str, Any],
    video: Flags,
    audio: Flags,
) -> None:
    """`GET /Items/{itemId}`, which emits `MediaSources` with no `fields` at all."""
    app, world = world_app
    as_user(app, world.everyone, policy)

    for item_id, expected in ((world.corpus[0], video), (world.tracks[0], audio)):
        answered = await client.get(f"/Items/{item_id}")
        assert answered.status_code == 200, answered.text
        body = dict(answered.json())
        assert body["MediaSources"], "the full body carries its sources unasked"
        for source in body["MediaSources"]:
            assert flags(source) == expected, body["Type"]


@pytest.mark.parametrize(
    "policy,video,audio", [row[1:] for row in SHAPES], ids=[row[0] for row in SHAPES]
)
async def test_the_item_list_carries_the_accounts_flags(
    client: httpx.AsyncClient,
    world_app: tuple[FastAPI, QueryWorld],
    policy: dict[str, Any],
    video: Flags,
    audio: Flags,
) -> None:
    """`GET /Items` - the route the shortfall was noticed on, and one of ten."""
    app, world = world_app
    as_user(app, world.everyone, policy)

    assert_rows(
        await sourced(client, "/Items", recursive="true", includeItemTypes="Movie,Audio,Episode"),
        video,
        audio,
    )


@pytest.mark.parametrize(
    "policy,video,audio", [row[1:] for row in SHAPES], ids=[row[0] for row in SHAPES]
)
async def test_latest_carries_the_accounts_flags(
    client: httpx.AsyncClient,
    world_app: tuple[FastAPI, QueryWorld],
    policy: dict[str, Any],
    video: Flags,
    audio: Flags,
) -> None:
    """`GET /Items/Latest`, whose answer is a bare array rather than an envelope."""
    app, world = world_app
    as_user(app, world.everyone, policy)

    assert_rows(await sourced(client, "/Items/Latest", limit=100), video, audio)


@pytest.mark.parametrize(
    "policy,video,audio", [row[1:] for row in SHAPES], ids=[row[0] for row in SHAPES]
)
async def test_resume_carries_the_accounts_flags(
    client: httpx.AsyncClient,
    world_app: tuple[FastAPI, QueryWorld],
    policy: dict[str, Any],
    video: Flags,
    audio: Flags,
) -> None:
    """`GET /UserItems/Resume`."""
    app, world = world_app
    as_user(app, world.everyone, policy)

    assert_rows(await sourced(client, "/UserItems/Resume"), video, audio)


@pytest.mark.parametrize(
    "policy,video,audio", [row[1:] for row in SHAPES], ids=[row[0] for row in SHAPES]
)
async def test_episodes_carry_the_accounts_flags(
    client: httpx.AsyncClient,
    world_app: tuple[FastAPI, QueryWorld],
    policy: dict[str, Any],
    video: Flags,
    audio: Flags,
) -> None:
    """`GET /Shows/{seriesId}/Episodes`."""
    app, world = world_app
    as_user(app, world.everyone, policy)

    assert_rows(await sourced(client, f"/Shows/{world.series[0].id}/Episodes"), video, audio)


@pytest.mark.parametrize(
    "policy,video,audio", [row[1:] for row in SHAPES], ids=[row[0] for row in SHAPES]
)
async def test_next_up_carries_the_accounts_flags(
    client: httpx.AsyncClient,
    world_app: tuple[FastAPI, QueryWorld],
    policy: dict[str, Any],
    video: Flags,
    audio: Flags,
) -> None:
    """`GET /Shows/NextUp`."""
    app, world = world_app
    as_user(app, world.everyone, policy)

    assert_rows(await sourced(client, "/Shows/NextUp"), video, audio)


@pytest.mark.parametrize(
    "policy,video,audio", [row[1:] for row in SHAPES], ids=[row[0] for row in SHAPES]
)
async def test_similar_carries_the_accounts_flags(
    client: httpx.AsyncClient,
    world_app: tuple[FastAPI, QueryWorld],
    policy: dict[str, Any],
    video: Flags,
    audio: Flags,
) -> None:
    """`GET /Items/{itemId}/Similar`."""
    app, world = world_app
    as_user(app, world.everyone, policy)

    assert_rows(await sourced(client, f"/Items/{world.corpus[0]}/Similar"), video, audio)


@pytest.mark.parametrize(
    "policy,video,audio", [row[1:] for row in SHAPES], ids=[row[0] for row in SHAPES]
)
async def test_instant_mix_carries_the_accounts_flags(
    client: httpx.AsyncClient,
    world_app: tuple[FastAPI, QueryWorld],
    policy: dict[str, Any],
    video: Flags,
    audio: Flags,
) -> None:
    """`GET /Items/{itemId}/InstantMix`, whose rows are always audio."""
    app, world = world_app
    as_user(app, world.everyone, policy)

    assert_rows(await sourced(client, f"/Items/{world.album}/InstantMix"), video, audio)


@pytest.mark.parametrize(
    "policy,video,audio", [row[1:] for row in SHAPES], ids=[row[0] for row in SHAPES]
)
async def test_playlist_entries_carry_the_accounts_flags(
    client: httpx.AsyncClient,
    world_app: tuple[FastAPI, QueryWorld],
    policy: dict[str, Any],
    video: Flags,
    audio: Flags,
) -> None:
    """`GET /Playlists/{playlistId}/Items` - the cross-library one, so both kinds are in it."""
    app, world = world_app
    as_user(app, world.everyone, policy)

    rows = await sourced(client, f"/Playlists/{world.cross_library_playlist.id}/Items")
    assert {row["Type"] for row in rows} == {"Movie", "Audio"}, "both kinds, or it proves one rule"
    assert_rows(rows, video, audio)


# ------------------------------------------------------------------------------------------
# Whose policy, and the two properties the rule does *not* have
# ------------------------------------------------------------------------------------------


async def test_the_policy_is_the_named_users_and_not_the_callers(
    client: httpx.AsyncClient, world_app: tuple[FastAPI, QueryWorld]
) -> None:
    """`userId` decides, so an administrator reading for a denied account sees that account's
    flags and reading for themselves sees their own.

    Measured on the reference in both directions, including the case with no `userId` at all -
    which is the **token holder's** policy and not "no policy", so `effective_user` is exactly
    the right resolution `[probe: tools/probe_playback_info.py, Jellyfin 10.11.11, 2026-09-02]`.
    """
    app, world = world_app
    with app.state.sessions.begin() as opened:
        UserRepository(opened).set_policy(
            world.restricted.id,
            {},
            {**world.restricted.policy_extra, VIDEO_TRANSCODING: False},
        )

    administrator = replace(world.everyone, is_administrator=True)
    app.dependency_overrides[require_user] = lambda: administrator

    for_them = await client.get(f"/Items/{world.corpus[0]}", params={"userId": world.restricted.id})
    assert for_them.status_code == 200, for_them.text
    assert flags(dict(for_them.json())["MediaSources"][0]) == (True, True, False)

    for_themselves = await client.get(f"/Items/{world.corpus[0]}")
    assert for_themselves.status_code == 200, for_themselves.text
    assert flags(dict(for_themselves.json())["MediaSources"][0]) == (True, True, True)


async def test_a_source_nothing_inspected_carries_the_flags_too(
    client: httpx.AsyncClient, world_app: tuple[FastAPI, QueryWorld]
) -> None:
    """An un-inspected source is not exempt, which is the half behaviours section 5's other row
    describes as three flags true: three flags true is the *permitted* account's answer.

    Measured on the reference against a fixture film of dummy bytes, which carries no runtime, no
    bitrate and no streams and still answers the account's own flags
    `[probe: tools/probe_playback_info.py, Jellyfin 10.11.11, 2026-09-02]`.

    The seeded world states an inspection for **every** file on purpose, so the state has to be
    made here: the probe rows of the films library are removed, which is exactly what a library
    scanned before 008 or a file added since looks like.
    """
    app, world = world_app
    with app.state.sessions.begin() as opened:
        for table in (models.MediaStreamRow, models.MediaProbe):
            opened.execute(delete(table).where(table.library_id == world.movies.id))

    as_user(app, world.everyone, {REMUXING: False})

    rows = await sourced(client, "/Items", recursive="true", includeItemTypes="Movie")
    bare = [
        row
        for row in rows
        if row["MediaSources"][0].get("RunTimeTicks") is None
        and not row["MediaSources"][0].get("MediaStreams")
    ]
    assert len(bare) == len(rows), "the removal left an inspection behind"
    for row in bare:
        assert flags(row["MediaSources"][0]) == (True, False, True)


# ------------------------------------------------------------------------------------------
# The structural half: every context filler, enumerated from the source
# ------------------------------------------------------------------------------------------


def build_context_calls() -> list[tuple[str, int, frozenset[str]]]:
    """Every `BuildContext(...)` in `src/atrium/api/`, with the keywords it passes.

    Read from the source rather than listed here, because a list of routes is exactly the thing
    that goes stale the day somebody adds the eleventh one.
    """
    found: list[tuple[str, int, frozenset[str]]] = []
    for module in sorted(API_PACKAGE.glob("*.py")):
        tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "BuildContext"
            ):
                names = frozenset(kw.arg for kw in node.keywords if kw.arg is not None)
                found.append((module.name, node.lineno, names))
    return found


def test_every_item_building_route_fills_the_policy() -> None:
    """The guard that survives a route being added, and the mechanism behaviours section 5 named.

    `BuildContext.policy` has no default, so a construction that omits it cannot be built at all;
    this asserts the same thing at the source, so the failure names the file and the line rather
    than arriving as a `TypeError` from whichever test happened to touch that route first.
    """
    calls = build_context_calls()
    assert len(calls) >= 13, f"only {len(calls)} BuildContext constructions found - parser broken?"
    missing = [(name, line) for name, line, keywords in calls if "policy" not in keywords]
    assert not missing, f"these BuildContext constructions name no policy: {missing}"


def test_the_context_refuses_to_be_built_without_a_policy() -> None:
    """The absence of a default is the mechanism, so it is asserted rather than assumed."""
    from atrium.api.item_dto import BuildContext

    with pytest.raises(TypeError):
        BuildContext(server_id="s" * 32)  # type: ignore[call-arg]
