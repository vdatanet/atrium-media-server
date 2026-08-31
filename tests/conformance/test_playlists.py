# SPDX-License-Identifier: GPL-3.0-or-later
"""`POST /Playlists`, at the boundary a client sees.

Every refusal here is asserted as **bytes and content type**, never as a status: this one route
answers four different `400` bodies from three layers, and a test that compared status codes would
pass against any three of them. The bodies are transcriptions of a measured run
`[probe: tools/probe_playlist_creation.py, Jellyfin 10.11.11, 2026-08-31]`, not derivations of what
this server happens to produce - which is the mistake 001 T16 found a passing test making.

AC-1, AC-2 and AC-3 land here; so does the `403` half of AC-19 on this feature's first route, and
the divergence behaviours section 3.19 records.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from atrium.api.deps import require_user
from atrium.config.paths import DataPaths
from atrium.db.item_queries import ItemQueryRepository
from atrium.db.repositories import PlaylistRepository, UserRepository
from atrium.domain.user import User
from atrium.server import create_app
from tests.conftest import data_dir
from tests.fixtures.query import QueryWorld, build_query_world

pytestmark = pytest.mark.conformance

HEX32 = re.compile(r"\A[0-9a-f]{32}\Z")

#: Well-formed and addresses nothing, exactly as the probe's does: a malformed identifier would
#: measure the binder instead of the id walk.
ABSENT_ID = "f" * 32

ADMIN_ID = "d" * 32

#: The four refusal bodies, byte for byte off the wire of a 10.11.11. `traceId` is per request by
#: definition (behaviours section 1.11), so it is the one member compared by shape.
MISSING_NAME = (
    "JSON deserialization for type "
    "'Jellyfin.Api.Models.PlaylistDtos.CreatePlaylistDto' "
    "was missing required properties including: 'Name'."
)
NULL_NAME = "The Name field is required."
UNKNOWN_MEDIA_TYPE = (
    "The JSON value could not be converted to Jellyfin.Data.Enums.MediaType. "
    "Path: $ | LineNumber: 0 | BytePositionInLine: 10."
)
CONTROLLER_BODY = b"Error processing request."


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


def validation_body(answered: httpx.Response) -> dict[str, Any]:
    """The problem-details document, with `traceId` checked for shape and then dropped."""
    body = json.loads(answered.content)
    assert re.fullmatch(r"00-[0-9a-f]{32}-[0-9a-f]{16}-00", body.pop("traceId")), body
    return body


def problem(errors: dict[str, list[str]]) -> dict[str, Any]:
    return {
        "type": "https://tools.ietf.org/html/rfc9110#section-15.5.1",
        "title": "One or more validation errors occurred.",
        "status": 400,
        "errors": errors,
    }


async def created_id(answered: httpx.Response) -> str:
    assert answered.status_code == 200, answered.content
    body = json.loads(answered.content)
    assert list(body) == ["Id"], body
    assert HEX32.match(body["Id"]), body
    return str(body["Id"])


async def item(client: httpx.AsyncClient, playlist_id: str) -> dict[str, Any]:
    answered = await client.get(f"/Items/{playlist_id}")
    assert answered.status_code == 200, answered.content
    found: dict[str, Any] = answered.json()
    return found


# --------------------------------------------------------------------------------------------
# AC-2 and the refusals: four `400` bodies on one route, from three layers
# --------------------------------------------------------------------------------------------


async def test_a_body_with_no_name_is_the_deserialisers_refusal_keyed_on_the_dollar(
    client: httpx.AsyncClient,
) -> None:
    """009 plan section 6.1 called this *"keyed on the property"*. It is keyed `"$"`.

    The reference refuses the whole document before any property is validated, and names the type
    it was building. The property key belongs to the next test, which is a different request.
    """
    answered = await client.post("/Playlists", json={"Ids": []})

    assert answered.status_code == 400
    assert answered.headers["content-type"] == "application/json; charset=utf-8"
    assert validation_body(answered) == problem({"$": [MISSING_NAME]})


async def test_a_null_name_is_a_different_refusal_keyed_on_the_property(
    client: httpx.AsyncClient,
) -> None:
    """Present and null is not absent, and the reference answers them at two different keys.

    Nothing in this repository had asked for the pair to be told apart; the framework here reports
    the two locations with two different spellings (`Name` and `name`), so a route that did not
    normalise them would send a snake_case key on exactly one of the two.
    """
    answered = await client.post("/Playlists", json={"Name": None})

    assert answered.status_code == 400
    assert validation_body(answered) == problem({"Name": [NULL_NAME]})


async def test_an_unrecognised_media_type_in_the_body_is_the_converters_refusal(
    client: httpx.AsyncClient,
) -> None:
    """009 T3's handoff: a `400` in the validation shape, not a dropped token.

    The byte position is the offset **inside the quoted token** - measured with a one-character
    value, below - which is what makes this sentence reproducible where section 1.11's parser
    message is not.
    """
    answered = await client.post("/Playlists", json={"Name": "x", "MediaType": "Nonsense"})

    assert answered.status_code == 400
    assert validation_body(answered) == problem({"$": [UNKNOWN_MEDIA_TYPE]})


async def test_the_media_type_refusals_position_follows_the_token_and_not_the_request(
    client: httpx.AsyncClient,
) -> None:
    """`3` for one character where eight characters give `10`: the quotes and the token."""
    answered = await client.post(
        "/Playlists",
        json={"Name": "a much longer name than the other request sent", "MediaType": "X"},
    )

    assert validation_body(answered)["errors"]["$"] == [
        UNKNOWN_MEDIA_TYPE.replace("BytePositionInLine: 10.", "BytePositionInLine: 3.")
    ]


@pytest.mark.parametrize("body", [{"Name": "x", "Ids": ["banana"]}, {"Name": "x", "UserId": "b"}])
async def test_a_malformed_identifier_is_the_binders_refusal_keyed_on_the_empty_string(
    client: httpx.AsyncClient, body: dict[str, Any]
) -> None:
    """The shape 007 already measured, reached here by two properties of one body."""
    answered = await client.post("/Playlists", json=body)

    assert answered.status_code == 400
    assert validation_body(answered) == problem({"": ["The supplied value is invalid."]})


async def test_no_refusal_of_this_body_names_the_action_parameter(
    client: httpx.AsyncClient,
) -> None:
    """The row 007's three routes carry and this one does not, because its body is optional.

    behaviours section 1.11 stated it as a property of a body refusal; it is a property of a
    *required* body refusal, and `POST /Playlists` is the route that separates the two.
    """
    for body in ({"Ids": []}, {"Name": None}, {"Name": "x", "Ids": ["banana"]}):
        answered = await client.post("/Playlists", json=body)
        assert list(validation_body(answered)["errors"]) != ["createPlaylistDto"]
        assert (
            "createPlaylistDto"
            not in validation_body(await client.post("/Playlists", json=body))["errors"]
        )


@pytest.mark.parametrize("name", ["", "   "])
async def test_an_empty_or_blank_name_creates_a_playlist_carrying_it(
    client: httpx.AsyncClient, name: str
) -> None:
    """AC-2's first half. The specification asserted `400` here until the gate measured it."""
    made = await created_id(await client.post("/Playlists", json={"Name": name}))

    assert (await item(client, made))["Name"] == name


# --------------------------------------------------------------------------------------------
# AC-3: the id walk, whose refusal depends on where the unknown id sits
# --------------------------------------------------------------------------------------------


async def test_an_unknown_id_before_any_resolvable_one_is_the_controllers_refusal(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    answered = await client.post(
        "/Playlists", json={"Name": "a", "Ids": [ABSENT_ID, world.tracks[0]]}
    )

    assert answered.status_code == 400
    assert answered.content == CONTROLLER_BODY
    assert answered.headers["content-type"] == "text/plain"


async def test_an_unknown_id_after_a_resolvable_one_is_skipped(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    made = await created_id(
        await client.post("/Playlists", json={"Name": "b", "Ids": [world.tracks[0], ABSENT_ID]})
    )

    assert (await item(client, made))["MediaType"] == "Audio"


async def test_a_media_type_makes_the_same_unknown_id_harmless(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """The walk only happens when the request names no media type - so the same list refuses or
    succeeds depending on a property that has nothing to do with the ids."""
    answered = await client.post(
        "/Playlists",
        json={"Name": "c", "Ids": [ABSENT_ID, world.tracks[0]], "MediaType": "Audio"},
    )

    assert answered.status_code == 200, answered.content


async def test_the_two_refusals_of_this_route_are_not_the_same_shape(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """The task's own title, held as one assertion: same status, three differences."""
    validation = await client.post("/Playlists", json={"Ids": []})
    controller = await client.post("/Playlists", json={"Name": "d", "Ids": [ABSENT_ID]})

    assert validation.status_code == controller.status_code == 400
    assert validation.headers["content-type"] != controller.headers["content-type"]
    assert validation.content != controller.content


# --------------------------------------------------------------------------------------------
# The media type, decided once (009 spec section 3.2)
# --------------------------------------------------------------------------------------------


async def test_a_playlist_created_empty_is_audio(client: httpx.AsyncClient) -> None:
    made = await created_id(await client.post("/Playlists", json={"Name": "empty"}))

    assert (await item(client, made))["MediaType"] == "Audio"


async def test_the_first_resolvable_id_settles_the_media_type(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    made = await created_id(
        await client.post("/Playlists", json={"Name": "film", "Ids": [world.corpus[0]]})
    )

    assert (await item(client, made))["MediaType"] == "Video"


async def test_the_bodys_media_type_outranks_the_contents(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    made = await created_id(
        await client.post(
            "/Playlists", json={"Name": "film", "Ids": [world.corpus[0]], "MediaType": "Audio"}
        )
    )

    assert (await item(client, made))["MediaType"] == "Audio"


# --------------------------------------------------------------------------------------------
# The query form, which the reference honours and which decides that the body is optional
# --------------------------------------------------------------------------------------------


async def test_a_name_in_the_query_creates_a_playlist_with_no_body_at_all(
    client: httpx.AsyncClient,
) -> None:
    made = await created_id(await client.post("/Playlists", params={"name": "from the query"}))

    assert (await item(client, made))["Name"] == "from the query"


async def test_the_query_name_beats_the_bodys(client: httpx.AsyncClient) -> None:
    made = await created_id(
        await client.post("/Playlists", params={"name": "query"}, json={"Name": "body"})
    )

    assert (await item(client, made))["Name"] == "query"


async def test_a_query_name_does_not_rescue_a_body_that_does_not_bind(
    client: httpx.AsyncClient,
) -> None:
    """Measured: the deserialiser refuses before the query is read, so plan section 6.1's first
    step really does belong to the model layer even though the property has a second source."""
    answered = await client.post("/Playlists", params={"name": "query"}, json={"Ids": []})

    assert validation_body(answered) == problem({"$": [MISSING_NAME]})


async def test_an_unrecognised_media_type_in_the_query_is_dropped_and_recorded(
    client: httpx.AsyncClient, app: FastAPI
) -> None:
    """The same value, refused by the body and ignored in the query: behaviours section 1.12."""
    made = await created_id(
        await client.post("/Playlists", params={"mediaType": "Nonsense"}, json={"Name": "q"})
    )

    assert (await item(client, made))["MediaType"] == "Audio"
    assert ("/Playlists", "mediaType=Nonsense") in app.state.ignored_parameters.counts


async def test_a_request_naming_no_name_anywhere_is_refused_rather_than_crashed(
    client: httpx.AsyncClient,
) -> None:
    """behaviours section 3.19: the reference answers `500` here, in these same bytes."""
    answered = await client.post("/Playlists")

    assert answered.status_code == 400
    assert answered.content == CONTROLLER_BODY
    assert answered.headers["content-type"] == "text/plain"


# --------------------------------------------------------------------------------------------
# AC-1 and AC-19's half on this route
# --------------------------------------------------------------------------------------------


async def test_a_created_playlist_appears_in_items_filtered_by_its_type(
    client: httpx.AsyncClient,
) -> None:
    """AC-1, which is the whole reason the item row exists (009 plan section 4.2)."""
    made = await created_id(await client.post("/Playlists", json={"Name": "listed"}))

    listed = await client.get(
        "/Items", params={"includeItemTypes": "Playlist", "recursive": "true"}
    )
    rows = {row["Id"]: row for row in listed.json()["Items"]}

    assert made in rows
    assert rows[made]["Type"] == "Playlist"


async def test_a_user_id_naming_somebody_else_is_the_reference_403_with_its_bytes(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """AC-19 on this feature's first route. The reference refuses it through the same helper it
    uses on the add route `[probe: tools/probe_playlist_visibility.py, Jellyfin 10.11.11,
    2026-08-31]`."""
    answered = await client.post(
        "/Playlists", json={"Name": "stolen", "UserId": world.restricted.id}
    )

    assert answered.status_code == 403
    assert answered.content == CONTROLLER_BODY
    assert answered.headers["content-type"] == "text/plain"


async def test_an_administrator_may_create_a_playlist_for_another_user(
    client: httpx.AsyncClient, harness: Harness, world: QueryWorld
) -> None:
    """The other half of the same rule, and the one that proves the refusal is about the caller."""
    as_user(harness, harness.admin)
    made = await created_id(
        await client.post("/Playlists", json={"Name": "for them", "UserId": world.everyone.id})
    )

    with harness.app.state.sessions.begin() as opened:
        stored = PlaylistRepository(opened, ItemQueryRepository(opened)).by_id(made, world.everyone)
    assert stored is not None
    assert stored.owner_user_id == world.everyone.id


# --------------------------------------------------------------------------------------------
# What the body stores beyond the name
# --------------------------------------------------------------------------------------------


async def test_the_create_body_stores_its_shares_and_its_public_flag(
    client: httpx.AsyncClient, harness: Harness, world: QueryWorld
) -> None:
    """`Users` is the only way v1 sets a share (009 spec section 3.2), so this is the whole of
    how spec section 3.7's second and third classes of caller come to exist."""
    made = await created_id(
        await client.post(
            "/Playlists",
            json={
                "Name": "shared",
                "IsPublic": True,
                "Users": [{"UserId": world.restricted.id, "CanEdit": True}],
            },
        )
    )

    with harness.app.state.sessions.begin() as opened:
        stored = PlaylistRepository(opened, ItemQueryRepository(opened)).by_id(made, world.everyone)
    assert stored is not None
    assert stored.is_public is True
    assert [(one.user_id, one.can_edit) for one in stored.shares] == [(world.restricted.id, True)]
