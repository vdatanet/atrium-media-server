# SPDX-License-Identifier: GPL-3.0-or-later
"""`GET /Items` and `GET /Items/{itemId}`, end to end, against the seeded world.

Three groups, and each holds something the layers below cannot:

* **The parameter battery** - one case per tier 1 and tier 2 parameter, each against a world
  slice built to be narrowed or reordered by it, failing if the parameter changes nothing
  (AC-16). Every case then runs once more with its parameter names case-mangled and must answer
  the identical body, which re-holds the canonicalisation of behaviours 1.15 on a real route.
* **The refusals** - the byte-identical `404` for an unknown and an invisible id (AC-8), the
  validation `400` for a malformed one, the measured `403` for a `userId` that is not the caller's,
  and the tier 3 parameter that is ignored, answered `200`, and recorded (AC-15).
* **The paging property re-held over HTTP** (AC-4's endpoint half) and the statement-count
  parity that keeps the whole route inside the repository's fixed budget.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import httpx
import pytest
from fastapi import FastAPI

from atrium.api.deps import require_user
from atrium.api.items import parse_kinds
from atrium.compat.query_params import IgnoredParameters
from atrium.config.paths import DataPaths
from atrium.db.repositories import UserRepository
from atrium.domain.items import ItemType
from atrium.domain.user import User
from atrium.library.identity import for_by_name
from atrium.server import create_app
from tests.conftest import QueryCounter, data_dir
from tests.fixtures.query import CORPUS_SIZE, QueryWorld, build_query_world

ADMIN_ID = "d" * 32


@dataclass(frozen=True)
class Harness:
    app: FastAPI
    world: QueryWorld
    admin: User


@pytest.fixture
def harness(tmp_path: Path) -> Iterator[Harness]:
    paths: DataPaths = data_dir(tmp_path / "atrium")
    built = create_app(paths)
    built.state.readiness.mark_ready()
    with built.state.sessions.begin() as opened:
        world = build_query_world(opened)
        admin = UserRepository(opened).add(
            User(id=ADMIN_ID, name="admin", is_administrator=True, enable_all_folders=True)
        )
    yield Harness(app=built, world=world, admin=admin)
    built.dependency_overrides.clear()
    built.state.db.dispose()


@pytest.fixture
def world(harness: Harness) -> QueryWorld:
    return harness.world


@pytest.fixture
def app(harness: Harness) -> FastAPI:
    harness.app.dependency_overrides[require_user] = lambda: harness.world.everyone
    return harness.app


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://atrium:8096") as opened:
        yield opened


def as_user(harness: Harness, user: User) -> None:
    harness.app.dependency_overrides[require_user] = lambda: user


def item_ids(body: dict[str, Any]) -> list[str]:
    return [one["Id"] for one in body["Items"]]


# ------------------------------------------------------------------------------------------
# The battery: every tier 1 and tier 2 parameter changes the answer (AC-16)
# ------------------------------------------------------------------------------------------

Check = Callable[[dict[str, Any], dict[str, Any], QueryWorld], None]


def _narrows(body: dict[str, Any], bare: dict[str, Any], _world: QueryWorld) -> None:
    assert 0 < body["TotalRecordCount"] < bare["TotalRecordCount"]


def _sorted_first_is_oldest(body: dict[str, Any], _bare: dict[str, Any], world: QueryWorld) -> None:
    assert item_ids(body)[0] == world.corpus[0]


def _sorted_first_is_newest(body: dict[str, Any], _bare: dict[str, Any], world: QueryWorld) -> None:
    assert item_ids(body)[0] == world.corpus[-1]


def _exactly_the_movies(body: dict[str, Any], bare: dict[str, Any], world: QueryWorld) -> None:
    assert body["TotalRecordCount"] == CORPUS_SIZE < bare["TotalRecordCount"]
    assert {one["Type"] for one in body["Items"]} == {"Movie"}


def _no_movies(body: dict[str, Any], _bare: dict[str, Any], world: QueryWorld) -> None:
    assert "Movie" not in {one["Type"] for one in body["Items"]}
    assert world.corpus[0] not in item_ids(body)


def _favourites(body: dict[str, Any], _bare: dict[str, Any], world: QueryWorld) -> None:
    assert set(item_ids(body)) == set(world.favourites)


def _watched(body: dict[str, Any], _bare: dict[str, Any], world: QueryWorld) -> None:
    assert set(item_ids(body)) == {handle.watched for handle in world.series}


def _without_watched(body: dict[str, Any], bare: dict[str, Any], world: QueryWorld) -> None:
    listed = set(item_ids(body))
    assert not listed & {handle.watched for handle in world.series}
    assert body["TotalRecordCount"] < bare["TotalRecordCount"]


def _resumable(body: dict[str, Any], _bare: dict[str, Any], world: QueryWorld) -> None:
    assert set(item_ids(body)) == set(world.resumable)


#: (label, query parameters, what must have changed). Built as functions of the world because
#: identifiers are derived, not literal. `userId` is exercised separately - its interesting
#: cases are refusals - and the four `enable*` options assert on the body rather than the count.
def battery(world: QueryWorld) -> list[tuple[str, dict[str, str], Check]]:
    series = world.series[0]
    return [
        (
            "parentId",
            {"parentId": series.id},
            lambda body, bare, w: (
                pytest.fail("parentId did not scope")
                if set(item_ids(body)) != set(series.seasons)
                else None
            ),
        ),
        (
            "recursive",
            {"parentId": series.id, "recursive": "true"},
            lambda body, bare, w: (
                pytest.fail("recursive did not descend")
                if set(item_ids(body)) != set(series.seasons) | set(series.episodes)
                else None
            ),
        ),
        (
            "startIndex",
            {"includeItemTypes": "Movie", "sortBy": "SortName", "limit": "5", "startIndex": "5"},
            lambda body, bare, w: (
                pytest.fail("startIndex did not move the window")
                if item_ids(body)[0] == w.corpus[0] or len(body["Items"]) != 5
                else None
            ),
        ),
        (
            "limit",
            {"includeItemTypes": "Movie", "limit": "5"},
            lambda body, bare, w: (
                pytest.fail("limit did not cap the page")
                if len(body["Items"]) != 5 or body["TotalRecordCount"] != CORPUS_SIZE
                else None
            ),
        ),
        ("sortBy", {"includeItemTypes": "Movie", "sortBy": "DateCreated"}, _sorted_first_is_oldest),
        (
            "sortOrder",
            {"includeItemTypes": "Movie", "sortBy": "DateCreated", "sortOrder": "Descending"},
            _sorted_first_is_newest,
        ),
        (
            "fields",
            {"ids": world.corpus[0], "fields": "Overview"},
            lambda body, bare, w: (
                pytest.fail("fields=Overview did not add the field")
                if "Overview" not in body["Items"][0]
                else None
            ),
        ),
        ("includeItemTypes", {"includeItemTypes": "Movie"}, _exactly_the_movies),
        ("excludeItemTypes", {"excludeItemTypes": "Movie"}, _no_movies),
        (
            "excludeItemIds",
            {"includeItemTypes": "Movie", "excludeItemIds": world.corpus[0]},
            lambda body, bare, w: (
                pytest.fail("excludeItemIds did not exclude")
                if body["TotalRecordCount"] != CORPUS_SIZE - 1 or w.corpus[0] in item_ids(body)
                else None
            ),
        ),
        (
            "mediaTypes",
            {"mediaTypes": "Video"},
            lambda body, bare, w: (
                pytest.fail("mediaTypes did not narrow")
                if {one["MediaType"] for one in body["Items"]} != {"Video"}
                or not 0 < body["TotalRecordCount"] < bare["TotalRecordCount"]
                else None
            ),
        ),
        ("searchTerm", {"searchTerm": "Paging Item 00"}, _narrows),
        (
            "ids",
            {"ids": f"{world.corpus[3]},{world.corpus[5]}"},
            lambda body, bare, w: (
                pytest.fail("ids did not select")
                if set(item_ids(body)) != {w.corpus[3], w.corpus[5]}
                else None
            ),
        ),
        ("genres", {"genres": "sci-fi"}, _narrows),
        ("genreIds", {"genreIds": for_by_name(ItemType.GENRE, "sci-fi")}, _narrows),
        (
            "studioIds",
            {"studioIds": for_by_name(ItemType.STUDIO, "A Studio")},
            lambda body, bare, w: (
                pytest.fail("studioIds did not select the studio's film")
                if item_ids(body) != [w.corpus[0]]
                else None
            ),
        ),
        ("artistIds", {"artistIds": world.album_artist}, _narrows),
        ("albumArtistIds", {"albumArtistIds": world.album_artist}, _narrows),
        ("albumIds", {"albumIds": world.album}, _narrows),
        (
            "personIds",
            {"personIds": for_by_name(ItemType.PERSON, "An Actor")},
            lambda body, bare, w: (
                pytest.fail("personIds did not select the credited film")
                if item_ids(body) != [w.corpus[0]]
                else None
            ),
        ),
        (
            "years",
            {"years": "1990"},
            lambda body, bare, w: (
                pytest.fail("years did not select the 1990 film")
                if item_ids(body) != [w.corpus[0]]
                else None
            ),
        ),
        ("nameStartsWith", {"nameStartsWith": "Paging"}, _narrows),
        (
            "nameStartsWithOrGreater",
            {"includeItemTypes": "Movie", "nameStartsWithOrGreater": "Paging Item 090"},
            _narrows,
        ),
        (
            "nameLessThan",
            {"includeItemTypes": "Movie", "nameLessThan": "Paging Item 010"},
            _narrows,
        ),
        (
            "minCommunityRating",
            {"minCommunityRating": "6.0"},
            lambda body, bare, w: (
                pytest.fail("minCommunityRating did not narrow to the well-rated")
                if set(item_ids(body)) != set(w.rated[2:])
                else None
            ),
        ),
        ("filters IsFavorite", {"filters": "IsFavorite"}, _favourites),
        ("filters IsPlayed", {"filters": "IsPlayed"}, _watched),
        ("filters IsUnplayed", {"filters": "IsUnplayed"}, _without_watched),
        ("filters IsResumable", {"filters": "IsResumable"}, _resumable),
        ("isPlayed", {"isPlayed": "true"}, _watched),
        ("isFavorite", {"isFavorite": "true"}, _favourites),
        (
            "enableUserData",
            {"ids": world.corpus[0], "enableUserData": "false"},
            lambda body, bare, w: (
                pytest.fail("enableUserData=false left UserData in place")
                if "UserData" in body["Items"][0]
                else None
            ),
        ),
        (
            "enableImages",
            {"ids": world.corpus[0], "enableImages": "false"},
            lambda body, bare, w: (
                pytest.fail("enableImages=false left the tag maps in place")
                if "ImageTags" in body["Items"][0] or "ImageBlurHashes" in body["Items"][0]
                else None
            ),
        ),
        (
            "imageTypeLimit",
            {"ids": series.id, "imageTypeLimit": "1"},
            lambda body, bare, w: (
                pytest.fail("imageTypeLimit did not cap the backdrops")
                if len(body["Items"][0]["BackdropImageTags"]) != 1
                else None
            ),
        ),
        (
            "enableImageTypes",
            {"ids": series.id, "enableImageTypes": "Primary"},
            lambda body, bare, w: (
                pytest.fail("enableImageTypes did not prune")
                if set(body["Items"][0]["ImageTags"]) != {"Primary"}
                or body["Items"][0]["BackdropImageTags"] != []
                else None
            ),
        ),
        (
            "enableTotalRecordCount",
            {"includeItemTypes": "Movie", "enableTotalRecordCount": "false"},
            lambda body, bare, w: (
                pytest.fail("enableTotalRecordCount=false did not report the honest zero")
                if body["TotalRecordCount"] != 0 or not body["Items"]
                else None
            ),
        ),
    ]


async def _bare(client: httpx.AsyncClient) -> dict[str, Any]:
    answered = await client.get("/Items", params={"limit": "1000"})
    assert answered.status_code == 200
    return dict(answered.json())


#: `battery()`'s labels, spelled once at module level so pytest can parametrize by name — the
#: battery itself needs the `world` fixture and cannot run at collection time. The previous
#: `range(36)` parametrization padded with a skip: a 37th case would silently never have run,
#: and a shrunk battery would have skipped quietly forever.
#: `test_the_battery_matches_its_label_list` keeps this tuple honest in both directions.
BATTERY_LABELS: Final = (
    "parentId",
    "recursive",
    "startIndex",
    "limit",
    "sortBy",
    "sortOrder",
    "fields",
    "includeItemTypes",
    "excludeItemTypes",
    "excludeItemIds",
    "mediaTypes",
    "searchTerm",
    "ids",
    "genres",
    "genreIds",
    "studioIds",
    "artistIds",
    "albumArtistIds",
    "albumIds",
    "personIds",
    "years",
    "nameStartsWith",
    "nameStartsWithOrGreater",
    "nameLessThan",
    "minCommunityRating",
    "filters IsFavorite",
    "filters IsPlayed",
    "filters IsUnplayed",
    "filters IsResumable",
    "isPlayed",
    "isFavorite",
    "enableUserData",
    "enableImages",
    "imageTypeLimit",
    "enableImageTypes",
    "enableTotalRecordCount",
)

#: Tier 1/2 parameters AC-16 covers through their own suites rather than this battery: `userId`
#: scopes every route of the feature and is asserted by the user-world and played-state tests.
COVERED_ELSEWHERE: Final = frozenset({"userId"})


def test_the_battery_matches_its_label_list(world: QueryWorld) -> None:
    """A case added to `battery()` without a label above would otherwise never run."""
    assert tuple(label for label, _, _ in battery(world)) == BATTERY_LABELS


def test_the_battery_covers_the_specifications_tier_1_and_2() -> None:
    """Spec section 3.3's "Every Tier 1 and Tier 2 parameter" (AC-16), held against the
    specification's own tier lists rather than restated by hand: a parameter added to either
    tier without a battery case fails here, one level below the acceptance map."""
    spec = Path(__file__).resolve().parents[2] / "specs" / "005-item-query-api" / "spec.md"
    text = spec.read_text(encoding="utf-8")
    tiers = text[text.index("**Tier 1") : text.index("**Tier 3")]
    parameters = set(re.findall(r"`([a-z][A-Za-z]+)`", tiers))
    exercised = {label.split()[0] for label in BATTERY_LABELS}
    assert parameters - exercised == COVERED_ELSEWHERE
    assert exercised <= parameters


@pytest.mark.parametrize("label", BATTERY_LABELS)
async def test_every_parameter_changes_the_answer_and_survives_mangled_casing(
    client: httpx.AsyncClient, world: QueryWorld, label: str
) -> None:
    """AC-16's endpoint half, and behaviours 1.15 re-held on the real route in the same breath:
    the mangled-casing rerun must produce the byte-identical body, not merely a passing one."""
    cases = {name: (params, check) for name, params, check in battery(world)}
    params, check = cases[label]

    bare = await _bare(client)
    answered = await client.get("/Items", params={**params, "limit": params.get("limit", "1000")})
    assert answered.status_code == 200, f"{label}: {answered.text[:200]}"
    check(dict(answered.json()), bare, world)

    mangled = {key.swapcase(): value for key, value in params.items()}
    mangled.setdefault(
        "LIMIT" if "limit" not in params else "limit".swapcase(), params.get("limit", "1000")
    )
    again = await client.get("/Items", params=mangled)
    assert again.status_code == 200, f"{label} mangled: {again.text[:200]}"
    assert again.json() == answered.json(), f"{label}: the mangled casing changed the answer"


# ------------------------------------------------------------------------------------------
# The refusals
# ------------------------------------------------------------------------------------------


async def test_ac8_unknown_and_invisible_ids_answer_byte_identical_404s(
    harness: Harness, client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """One line of code produces both, and the bytes prove it - the traceId is per-request by
    definition and masked the way behaviours 1.11 masks it."""
    as_user(harness, world.restricted)
    unknown = await client.get("/Items/" + "f" * 32)
    invisible = await client.get("/Items/" + world.series[0].episodes[0])

    assert unknown.status_code == invisible.status_code == 404

    def masked(payload: bytes) -> bytes:
        body = json.loads(payload)
        assert body["traceId"], "a problem-details body carries a traceId"
        body["traceId"] = "{trace-id}"
        return json.dumps(body).encode()

    assert masked(unknown.content) == masked(invisible.content)


async def test_ac15_a_private_playlist_is_absent_from_another_users_items(
    harness: Harness, client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """009 AC-15, asserted **through `/Items`** and not only through a direct fetch.

    That is the whole point of T6 and of this list's gate finding 2: the playlist routes are
    careful by construction and this listing is the one beside them that was not, because
    `_library_permitted` exempts a row with no library and a playlist has none. A clause proven
    only by the route that knows about playlists is a clause the leaking route never crossed.

    Measured in the same three classes on the reference: a private playlist is absent from another
    user's `/Items?includeItemTypes=Playlist`, a shared one and a public one are present
    `[probe: tools/probe_playlist_visibility.py, Jellyfin 10.11.11, 2026-08-31]`
    `[probe: tools/probe_playlist_shares.py, Jellyfin 10.11.11, 2026-08-31]`.
    """
    as_user(harness, world.restricted)
    listed = await client.get(
        "/Items", params={"includeItemTypes": "Playlist", "limit": "1000", "recursive": "true"}
    )
    assert listed.status_code == 200
    body = listed.json()
    shown = set(item_ids(body))
    assert body["TotalRecordCount"] == len(shown), "the count follows the predicate, not the world"

    assert world.private_playlist.id not in shown, "a private playlist reached a second user"
    assert world.public_playlist.id in shown
    assert world.shared_playlist.id in shown
    assert world.read_only_playlist.id in shown


async def test_ac15_an_unreachable_playlist_answers_404_by_id(
    harness: Harness, client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """AC-15's second half, in the shape AC-8 fixed: the invisible id and the unknown one are one
    refusal, so a client cannot learn a playlist exists by the way it is refused."""
    as_user(harness, world.nobody)
    refused = await client.get("/Items/" + world.private_playlist.id)
    unknown = await client.get("/Items/" + "f" * 32)
    assert refused.status_code == unknown.status_code == 404
    assert refused.json()["title"] == unknown.json()["title"]

    allowed = await client.get("/Items/" + world.public_playlist.id)
    assert allowed.status_code == 200
    assert allowed.json()["Type"] == "Playlist"


async def test_an_administrator_gets_no_read_on_a_playlist_they_do_not_own(
    harness: Harness, client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """Spec §3.7's last row, which the fixture world cannot express because it has no
    administrator: deletion is the **one** operation an administrator may perform on a playlist
    they do not own, and reading is not among the others
    `[source: Jellyfin.Api/Controllers/PlaylistsController.cs:132-134, 422-424, 461-463 @
    v10.11.11]`. So `_visible_to`'s fourth clause has no administrator branch, and this is the
    test that fails if one is ever added for convenience.
    """
    as_user(harness, harness.admin)
    listed = await client.get(
        "/Items", params={"includeItemTypes": "Playlist", "limit": "1000", "recursive": "true"}
    )
    assert set(item_ids(listed.json())) == {world.public_playlist.id}
    assert (await client.get("/Items/" + world.private_playlist.id)).status_code == 404


async def test_an_administrator_naming_a_user_sees_that_users_playlists(
    harness: Harness, client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """`userId` is whose visibility applies, and the fourth clause is inside that visibility rather
    than beside it - so it moves with the named user instead of staying with the caller."""
    as_user(harness, harness.admin)
    answered = await client.get(
        "/Items",
        params={
            "includeItemTypes": "Playlist",
            "userId": world.everyone.id,
            "limit": "1000",
            "recursive": "true",
        },
    )
    assert answered.status_code == 200
    assert set(item_ids(answered.json())) == {one.id for one in world.playlists}


async def test_media_types_over_playlists_reads_the_stored_row(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """The second half of T6, over HTTP. `mediaTypes=` is answered from the type for thirteen
    types and from the row for the fourteenth, and the world's one `Audio` playlist against its
    four `Video` ones is what tells a row read from a type-level guess
    `[probe: tools/probe_playlist_media_type.py, Jellyfin 10.11.11, 2026-08-31]`.
    """

    async def playlists_for(media: str) -> set[str]:
        answered = await client.get(
            "/Items",
            params={
                "includeItemTypes": "Playlist",
                "mediaTypes": media,
                "limit": "1000",
                "recursive": "true",
            },
        )
        assert answered.status_code == 200
        return set(item_ids(answered.json()))

    assert await playlists_for("Audio") == {world.public_playlist.id}
    assert await playlists_for("Video") == {
        one.id for one in world.playlists if one.media_type == "Video"
    }
    assert await playlists_for("audio") == await playlists_for("Audio")
    assert await playlists_for("Unknown") == set()


async def test_a_listed_playlist_reports_the_media_type_it_was_filtered_by(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """The filter and the body have to agree, and until T6 they could not: nothing on the `/Items`
    path filled `HydratedItem.media_type`, so every playlist listed here answered `Audio` from
    `MEDIA_TYPE_OF` while the row said otherwise. A `mediaTypes=Video` answer carrying
    `MediaType: "Audio"` is a listing disagreeing with itself, which is worse than the gap the
    filter closed `[probe: tools/probe_playlist_media_type.py, Jellyfin 10.11.11, 2026-08-31]`.
    """
    listed = await client.get(
        "/Items", params={"includeItemTypes": "Playlist", "limit": "1000", "recursive": "true"}
    )
    stored = {one.id: one.media_type for one in world.playlists}
    assert {one["Id"]: one["MediaType"] for one in listed.json()["Items"]} == stored
    assert set(stored.values()) == {"Audio", "Video"}, "a world of one media type proves nothing"

    bare = await client.get("/Items/" + world.private_playlist.id)
    assert bare.json()["MediaType"] == world.private_playlist.media_type == "Video"


async def test_a_malformed_id_is_the_validation_400(client: httpx.AsyncClient) -> None:
    answered = await client.get("/Items/not-an-id")
    assert answered.status_code == 400
    body = answered.json()
    assert body["title"] == "One or more validation errors occurred."
    assert "errors" in body and "traceId" in body


async def test_a_malformed_id_inside_a_list_parameter_is_a_400_too(
    client: httpx.AsyncClient,
) -> None:
    """The token-versus-type line: `ids` values are typed, not enum tokens to drop."""
    answered = await client.get("/Items", params={"ids": "not-an-id"})
    assert answered.status_code == 400
    assert answered.json()["errors"], "the errors map names the parameter"


async def test_an_unknown_or_invisible_parent_is_the_same_404(
    harness: Harness, client: httpx.AsyncClient, world: QueryWorld
) -> None:
    as_user(harness, world.restricted)
    unknown = await client.get("/Items", params={"parentId": "f" * 32})
    invisible = await client.get("/Items", params={"parentId": world.series[0].id})
    assert unknown.status_code == invisible.status_code == 404


async def test_user_id_of_somebody_else_is_the_controller_403(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """009 AC-19, on 005's route: the measured bytes, and nothing about the other user.

    This asserted `content == b""` from 005 until 009 measured the refusal against a real
    non-administrator - the reference sends the controller's own 25 bytes, and the assertion and
    this test's own name moved with the handler
    `[probe: tools/probe_playlist_visibility.py, Jellyfin 10.11.11, 2026-08-31]`.
    """
    answered = await client.get("/Items", params={"userId": world.restricted.id})
    assert answered.status_code == 403
    assert answered.content == b"Error processing request."
    # The charset Starlette would append is the whole reason `controller_error` sets the header
    # itself, and a test that only compared bodies is what let the empty one stand for a feature.
    assert answered.headers["content-type"] == "text/plain"


async def test_user_id_of_oneself_is_allowed(client: httpx.AsyncClient, world: QueryWorld) -> None:
    answered = await client.get("/Items", params={"userId": world.everyone.id, "limit": "1"})
    assert answered.status_code == 200


async def test_an_administrator_queries_with_the_named_users_visibility(
    harness: Harness, client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """`userId` is *whose visibility applies* (spec 3.3 tier 1), not merely an access check."""
    as_user(harness, harness.admin)
    answered = await client.get("/Items", params={"userId": world.restricted.id, "limit": "1000"})
    assert answered.status_code == 200
    types = {one["Type"] for one in answered.json()["Items"]}
    assert "Movie" in types
    assert "Episode" not in types, "the restricted user cannot see the shows library"


async def test_ac15_a_tier_3_parameter_is_ignored_answered_and_recorded(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    bare = await _bare(client)
    answered = await client.get("/Items", params={"limit": "1000", "isMovie": "true"})
    assert answered.status_code == 200
    assert answered.json()["TotalRecordCount"] == bare["TotalRecordCount"], (
        "a tier 3 parameter must not filter"
    )
    recorded = app.state.ignored_parameters.counts
    assert ("/Items", "isMovie") in recorded


async def test_an_unrecognised_sort_token_drops_and_is_recorded(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    """behaviours 1.12 on the real route: the token drops, the request succeeds, the trail
    exists."""
    answered = await client.get("/Items", params={"sortBy": "Nonsense", "limit": "1"})
    assert answered.status_code == 200
    assert ("/Items", "sortBy=Nonsense") in app.state.ignored_parameters.counts


async def test_a_real_kind_this_version_cannot_produce_narrows_to_nothing(
    client: httpx.AsyncClient,
) -> None:
    """`BoxSet` is a `BaseItemKind`, so the filter holds and matches nothing - unlike a
    dropped nonsense token, which would have returned the whole world.

    **This test asked `Playlist` until 009 T3**, and it would have gone on passing for the wrong
    reason: `Playlist` is now a type of this domain, so the token is a real filter over a world
    that happens to hold no playlists, which is a different mechanism answering with the same
    zero. The token has to name a kind the domain still does not have.
    """
    answered = await client.get("/Items", params={"includeItemTypes": "BoxSet"})
    assert answered.status_code == 200
    assert answered.json()["TotalRecordCount"] == 0
    assert answered.json()["Items"] == []


async def test_the_playlist_kind_is_now_this_domains_own(client: httpx.AsyncClient) -> None:
    """The other half of the test above: `Playlist` binds to a type rather than to the reference's
    vocabulary, so nothing is recorded as an ignored token and the filter is a real one."""
    assert parse_kinds("Playlist", "includeItemTypes", IgnoredParameters(), "/Items") == frozenset(
        {ItemType.PLAYLIST}
    )
    ignored = IgnoredParameters()
    assert parse_kinds("BoxSet", "includeItemTypes", ignored, "/Items") == frozenset()
    assert not ignored.counts, "a real BaseItemKind is not an ignored token"


async def test_an_oversized_limit_is_served_not_clamped(client: httpx.AsyncClient) -> None:
    """Plan section 7: the reference imposes no ceiling and inventing one is a delta."""
    answered = await client.get("/Items", params={"limit": "100000"})
    assert answered.status_code == 200
    assert len(answered.json()["Items"]) == answered.json()["TotalRecordCount"]


# ------------------------------------------------------------------------------------------
# The shapes, end to end
# ------------------------------------------------------------------------------------------


async def test_ac2_every_list_row_carries_user_data_with_key_and_item_id(
    client: httpx.AsyncClient,
) -> None:
    body = await _bare(client)
    for row in body["Items"]:
        assert row["UserData"]["Key"] == row["Id"]
        assert row["UserData"]["ItemId"] == row["Id"]
        assert row["ChannelId"] is None, "the explicit null travels on every row"


async def test_ac3_gated_fields_are_absent_bare_and_present_asked_over_http(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    bare = await client.get("/Items", params={"ids": world.corpus[0]})
    asked = await client.get(
        "/Items", params={"ids": world.corpus[0], "fields": "Overview,Genres,People"}
    )
    bare_row, asked_row = bare.json()["Items"][0], asked.json()["Items"][0]
    for name in ("Overview", "Genres", "GenreItems", "People"):
        assert name not in bare_row
        assert name in asked_row


async def test_the_item_route_emits_everything_unasked(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """Spec 3.2: `Fields` has nothing left to add to a full body."""
    answered = await client.get(f"/Items/{world.corpus[0]}")
    assert answered.status_code == 200
    body = answered.json()
    for name in (
        "Overview",
        "Genres",
        "People",
        "Studios",
        "SortName",
        "Path",
        "Etag",
        "ProviderIds",
        "ExternalUrls",
        "DateCreated",
        "PrimaryImageAspectRatio",
    ):
        assert name in body, f"{name} missing from the full body"
    assert body["ChannelId"] is None


async def test_a_series_full_body_carries_the_subtree_numbers(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    answered = await client.get(f"/Items/{world.series[0].id}")
    body = answered.json()
    assert body["ChildCount"] == len(world.series[0].seasons)
    assert body["RecursiveItemCount"] == len(world.series[0].episodes)
    assert "DateLastMediaAdded" in body


async def test_a_by_name_item_answers_on_the_item_route(
    client: httpx.AsyncClient,
) -> None:
    """`GET /Items/{yearId}` was T8's reason to create `Year` rows at all; the route half."""
    answered = await client.get("/Items/" + for_by_name(ItemType.GENRE, "sci-fi"))
    assert answered.status_code == 200
    body = answered.json()
    assert body["Type"] == "Genre"
    assert "IsFolder" not in body, "a by-name row has no IsFolder (measured)"


async def test_ac4_paging_over_http_visits_every_movie_exactly_once(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    seen: list[str] = []
    for start in range(0, CORPUS_SIZE, 7):
        page = await client.get(
            "/Items",
            params={
                "includeItemTypes": "Movie",
                "sortBy": "SortName",
                "startIndex": str(start),
                "limit": "7",
            },
        )
        body = page.json()
        assert body["StartIndex"] == start
        assert body["TotalRecordCount"] == CORPUS_SIZE
        seen.extend(item_ids(body))
    assert len(seen) == len(set(seen)) == CORPUS_SIZE
    assert set(seen) == set(world.corpus)


async def test_the_statement_count_is_page_size_independent_over_http(
    harness: Harness, client: httpx.AsyncClient, query_counter: QueryCounter
) -> None:
    """The route adds a fixed overhead on top of the repository's fixed budget - the counter
    holds parity, not a number, because the number belongs to `test_item_queries`."""
    with query_counter.watching(harness.app.state.db):
        small = await client.get("/Items", params={"limit": "1"})
        first = len(query_counter)
        query_counter.reset()
        large = await client.get("/Items", params={"limit": "50"})
        second = len(query_counter)
    assert small.status_code == large.status_code == 200
    assert first == second, query_counter.report()
