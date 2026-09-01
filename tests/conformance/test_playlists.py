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
from atrium.db.repositories import (
    ItemRepository,
    LibraryRepository,
    PlaylistRepository,
    UserRepository,
)
from atrium.domain.items import CollectionType, Item, ItemType, MediaSource
from atrium.domain.library import Library
from atrium.domain.user import User
from atrium.library import identity
from atrium.server import create_app
from tests.conftest import data_dir
from tests.fixtures.query import QueryWorld, build_query_world

pytestmark = pytest.mark.conformance

HEX32 = re.compile(r"\A[0-9a-f]{32}\Z")

#: Well-formed and addresses nothing, exactly as the probe's does: a malformed identifier would
#: measure the binder instead of the id walk.
ABSENT_ID = "f" * 32

#: `Guid.Empty`, and a class of its own: refused where `ABSENT_ID` is skipped (T10).
EMPTY_GUID = "0" * 32

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


# --------------------------------------------------------------------------------------------
# `GET /Playlists/{playlistId}/Items` - the one door (T9)
# --------------------------------------------------------------------------------------------
#
# The width, the envelope and every refusal below are a transcription of one measured run
# `[probe: tools/probe_playlist_read.py, Jellyfin 10.11.11, 2026-09-01]`, not of what this server
# happens to produce.


async def rows(client: httpx.AsyncClient, playlist_id: str, **params: Any) -> dict[str, Any]:
    answered = await client.get(f"/Playlists/{playlist_id}/Items", params=params)
    assert answered.status_code == 200, answered.content
    body: dict[str, Any] = json.loads(answered.content)
    return body


async def test_ac4_every_row_carries_a_playlist_item_id_equal_to_its_id(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """AC-4, on the serialised body rather than on a model.

    009 spec section 3.1's whole finding: the field the reference answers from is a cache of the
    resolved item's id, so `PlaylistItemId` is not an identifier of its own. Asserted as equality
    per row *and* as the identity of the two lists, because a route that emitted the item id in
    the wrong position or on the wrong row would satisfy one and not the other.
    """
    body = await rows(client, world.private_playlist.id)
    assert body["Items"], body
    for row in body["Items"]:
        assert row["PlaylistItemId"] == row["Id"], row
    assert [row["PlaylistItemId"] for row in body["Items"]] == list(world.private_playlist.entries)


async def test_the_property_sits_immediately_after_id_and_on_no_other_route(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """Measured wire position, and measured absence.

    On the reference a playlist row carries thirty-two property names where the same track through
    `/Items` carries thirty-one. The count is a fact about that library's items, so what is
    asserted here is the *shape* of the difference rather than the number: the two directions of
    the subtraction, one giving exactly `PlaylistItemId` and the other nothing at all, on the same
    item down both routes `[probe: tools/probe_playlist_read.py, Jellyfin 10.11.11, 2026-09-01]`.

    Position is part of the contract for the same reason it is on the login body: JSON key order
    is what a client reading the response by eye sees first, and the reference puts this property
    immediately after `Id`.
    """
    body = await rows(client, world.private_playlist.id)
    keys = list(body["Items"][0])
    assert keys[keys.index("Id") + 1] == "PlaylistItemId", keys

    entry = world.private_playlist.entries[0]
    listed = await client.get("/Items", params={"ids": entry, "recursive": "true"})
    assert listed.status_code == 200, listed.content
    row = json.loads(listed.content)["Items"][0]
    assert "PlaylistItemId" not in row, row
    assert set(keys) - set(row) == {"PlaylistItemId"}
    assert not set(row) - set(keys)


async def test_ac8_the_order_is_the_playlists_and_no_sort_parameter_is_declared(
    client: httpx.AsyncClient, app: FastAPI, world: QueryWorld
) -> None:
    """AC-8, both halves: the order, and the absence of the lever that could change it.

    The second half is asserted against the **generated OpenAPI document** rather than by sending
    a `sortBy` and finding the order unchanged. Two reasons, and they are the same reason: a route
    that accepted the parameter and happened to sort by the playlist's order would pass the weaker
    test, and the document is literally where a client discovers a capability - which is the thing
    Principle I forbids this route to have. Measured for completeness anyway:
    `sortBy=SortName&sortOrder=Descending` answers `200` in the playlist's own order
    `[probe: tools/probe_playlist_read.py, Jellyfin 10.11.11, 2026-09-01]`.
    """
    body = await rows(client, world.private_playlist.id)
    assert [row["Id"] for row in body["Items"]] == list(world.private_playlist.entries)

    operation = app.openapi()["paths"]["/Playlists/{playlistId}/Items"]["get"]
    declared = {one["name"] for one in operation["parameters"] if one["in"] == "query"}
    assert declared == {
        "userId",
        "startIndex",
        "limit",
        "fields",
        "enableImages",
        "enableUserData",
        "imageTypeLimit",
        "enableImageTypes",
    }


async def test_the_count_is_taken_before_paging_and_after_filtering(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """Plan section 6.5 step 4, and the only order that lets a client page."""
    whole = await rows(client, world.private_playlist.id)
    assert whole["TotalRecordCount"] == len(world.private_playlist.entries)
    assert whole["StartIndex"] == 0

    paged = await rows(client, world.private_playlist.id, startIndex=1, limit=2)
    assert [row["Id"] for row in paged["Items"]] == list(world.private_playlist.entries[1:3])
    assert paged["TotalRecordCount"] == len(world.private_playlist.entries)
    assert paged["StartIndex"] == 1

    past = await rows(client, world.private_playlist.id, startIndex=99, limit=2)
    assert past["Items"] == []
    assert past["TotalRecordCount"] == len(world.private_playlist.entries)
    assert past["StartIndex"] == 99


async def test_ac17_a_reader_is_shown_only_the_entries_they_can_reach(
    client: httpx.AsyncClient, harness: Harness, world: QueryWorld
) -> None:
    """AC-17's first half, which is 009's second divergence (behaviours section 3.17).

    The reference hands this reader every row and counts them all, because the filter in front of
    its entries is a parental-rating check and not a library one. Atrium omits them; the survivors
    keep their order and their entry ids, and the count follows the omission.
    """
    playlist = world.cross_library_playlist
    assert playlist.beyond_restricted, "the fixture must hold an unreachable entry"

    as_user(harness, world.restricted)
    body = await rows(client, playlist.id)

    assert [row["Id"] for row in body["Items"]] == list(playlist.restricted_sees)
    assert [row["PlaylistItemId"] for row in body["Items"]] == list(playlist.restricted_sees)
    assert body["TotalRecordCount"] == len(playlist.restricted_sees)
    assert body["TotalRecordCount"] < len(playlist.entries)


async def test_ac16_naming_another_user_is_the_controllers_own_twenty_five_bytes(
    client: httpx.AsyncClient, harness: Harness, world: QueryWorld
) -> None:
    """AC-16 and behaviours section 3.16, on the route the reference leaves open.

    **The reference answers `200` here** - a restricted user reads any private playlist by naming
    its owner, where the same parameter on the same controller's *write* route answers `403`
    `[probe: tools/probe_playlist_visibility.py, Jellyfin 10.11.11, 2026-09-01]`. Atrium answers
    the reference's own refusal, in the reference's own bytes.

    Asserted as bytes **and** content type, because a `403` is two shapes and only the header
    separates them (009 T2).
    """
    as_user(harness, world.restricted)
    answered = await client.get(
        f"/Playlists/{world.private_playlist.id}/Items",
        params={"userId": world.everyone.id},
    )
    assert answered.status_code == 403
    assert answered.content == CONTROLLER_BODY
    assert len(answered.content) == 25
    assert answered.headers["content-type"] == "text/plain"


async def test_an_administrator_may_name_a_user_and_gets_that_users_view(
    client: httpx.AsyncClient, harness: Harness, world: QueryWorld
) -> None:
    """AC-16's other half, and the one that proves `userId` moves the whole predicate.

    An administrator naming `restricted` sees what `restricted` sees - not what an administrator
    would see, and not everything: 009 plan section 6.5 step 3 says the visibility clause has no
    administrator branch, so naming a user *is* the only way an administrator reaches a playlist
    they neither own nor are shared.
    """
    as_user(harness, harness.admin)
    body = await rows(client, world.cross_library_playlist.id, userId=world.restricted.id)
    assert [row["Id"] for row in body["Items"]] == list(
        world.cross_library_playlist.restricted_sees
    )


async def test_an_administrator_who_is_none_of_the_three_classes_reads_nothing(
    client: httpx.AsyncClient, harness: Harness, world: QueryWorld
) -> None:
    """Spec section 3.7's last row, and the hole `by_id` leaves open on purpose.

    `PlaylistRepository.by_id` hands an administrator the row it would refuse anybody else, so
    that T12's deletion is writable at all. This route calls `may_read` on what comes back, and
    this is the test that fails if a later change drops that call.
    """
    as_user(harness, harness.admin)
    answered = await client.get(f"/Playlists/{world.private_playlist.id}/Items")
    assert answered.status_code == 404, answered.content
    assert answered.content == b'"Playlist not found"'


async def test_a_public_playlist_is_readable_by_anybody(
    client: httpx.AsyncClient, harness: Harness, world: QueryWorld
) -> None:
    """Spec section 3.7's fourth class, which no other seeded playlist can express.

    **Two readers, because readable and readable-in-full are different questions here.** The
    administrator is none of the first three classes and is refused every other playlist in this
    file (`test_an_administrator_who_is_none_of_the_three_classes_reads_nothing`), so a `200`
    carrying all three entries is `is_public` and nothing else. `restricted` proves the *other*
    half at the same time: the public playlist holds the three tracks, that user's one library is
    Films, and the divergence of AC-17 therefore empties a playlist it does not hide - `200` with
    nothing in it, which is a different answer from the `404` a private one gives.
    """
    as_user(harness, harness.admin)
    body = await rows(client, world.public_playlist.id)
    assert [row["Id"] for row in body["Items"]] == list(world.public_playlist.entries)
    assert body["TotalRecordCount"] == len(world.public_playlist.entries)

    as_user(harness, world.restricted)
    empty = await rows(client, world.public_playlist.id)
    assert empty["Items"] == []
    assert empty["TotalRecordCount"] == 0


@pytest.mark.parametrize(
    "case",
    ["absent", "not-a-playlist", "private-to-this-reader"],
)
async def test_three_requests_are_one_refusal_and_it_is_the_fourth_shape(
    client: httpx.AsyncClient, harness: Harness, world: QueryWorld, case: str
) -> None:
    """The finding this task was for: the `404` here is **not** problem details.

    Measured, `GET /Playlists/{id}/Items` answers the JSON-encoded bare string
    `"Playlist not found"` - `application/json; charset=utf-8`, 20 bytes - for an id that
    addresses nothing, for a real item that is not a playlist, and for a playlist this reader may
    not see `[probe: tools/probe_playlist_read.py, Jellyfin 10.11.11, 2026-09-01]`
    `[probe: tools/probe_playlist_visibility.py, Jellyfin 10.11.11, 2026-09-01]`. One body for
    three causes, which is what makes the private playlist undisclosable.

    Everything else in this project answers a handler's `404` with problem details, and
    `/Items/{itemId}` still does - on the very same playlist. The two routes disagree on purpose.
    """
    if case == "absent":
        target = ABSENT_ID
    elif case == "not-a-playlist":
        target = world.private_playlist.entries[0]
    else:
        target = world.private_playlist.id
        as_user(harness, world.restricted)

    answered = await client.get(f"/Playlists/{target}/Items")
    assert answered.status_code == 404, answered.content
    assert answered.content == b'"Playlist not found"'
    assert len(answered.content) == 20
    assert answered.headers["content-type"] == "application/json; charset=utf-8"


async def test_a_malformed_playlist_id_is_the_binders_four_hundred_not_this_routes_refusal(
    client: httpx.AsyncClient,
) -> None:
    """The fourth request, and it never reaches the route at all.

    Measured on the reference: `400` in the validation shape, where the three above are `404`.
    Typing `playlistId` as an identifier is what produces it, and a `str` there would have turned
    a measured `400` into a `404` on the one route where the two are already unusually split.

    **And it is the *path* parameter's sentence, not the body's.** A malformed identifier inside
    `POST /Playlists`'s body is `{"": ["The supplied value is invalid."]}` - the four refusals at
    the top of this file - where the same malformation in a path segment names the parameter and
    quotes the value back. Both are behaviours section 1.11 and they are not the same string
    `[probe: tools/probe_playlist_read.py, Jellyfin 10.11.11, 2026-09-01]`.
    """
    answered = await client.get("/Playlists/not-an-identifier/Items")
    assert answered.status_code == 400, answered.content
    assert validation_body(answered) == problem(
        {"playlistId": ["The value 'not-an-identifier' is not valid."]}
    )
    assert answered.headers["content-type"] == "application/json; charset=utf-8"


async def test_the_declared_parameters_are_honoured(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """`fields`, `enableUserData` and `enableImages`, all three measured as live on this route.

    Plan section 6.5 step 4 assumes 005's envelope machinery applies unchanged; this is the test
    that says so, and it exists because "the standard list envelope" is a sentence rather than an
    assertion.
    """
    bare = await rows(client, world.private_playlist.id)
    assert all("Path" not in row for row in bare["Items"])
    assert all("UserData" in row for row in bare["Items"])

    asked = await rows(client, world.private_playlist.id, fields="Path")
    assert any("Path" in row for row in asked["Items"])

    quiet = await rows(client, world.private_playlist.id, enableUserData="false")
    assert all("UserData" not in row for row in quiet["Items"])

    dark = await rows(client, world.private_playlist.id, enableImages="false")
    assert all("ImageTags" not in row for row in dark["Items"])


# --------------------------------------------------------------------------------------------
# `POST` and `DELETE /Playlists/{playlistId}/Items` - adding and removing (T10)
# --------------------------------------------------------------------------------------------
#
# Every case below is a transcription of a measured run
# `[probe: tools/probe_playlist_expansion.py, Jellyfin 10.11.11, 2026-09-01]`
# `[probe: tools/probe_playlist_add_remove.py, Jellyfin 10.11.11, 2026-09-01]`.


async def add(
    client: httpx.AsyncClient, playlist_id: str, ids: list[str], **params: Any
) -> httpx.Response:
    return await client.post(
        f"/Playlists/{playlist_id}/Items", params={"ids": ",".join(ids), **params}
    )


async def drop(
    client: httpx.AsyncClient, playlist_id: str, entry_ids: list[str] | None = None
) -> httpx.Response:
    params = {} if entry_ids is None else {"entryIds": ",".join(entry_ids)}
    return await client.delete(f"/Playlists/{playlist_id}/Items", params=params)


async def entries(client: httpx.AsyncClient, playlist_id: str) -> list[str]:
    body = await rows(client, playlist_id)
    return [row["Id"] for row in body["Items"]]


async def a_new_playlist(client: httpx.AsyncClient, **params: Any) -> str:
    """An empty playlist through the route that makes one, so no test writes its own rows."""
    return await created_id(await client.post("/Playlists", params={"name": "T10", **params}))


async def added(client: httpx.AsyncClient, ids: list[str]) -> list[str]:
    """What one add lands in a fresh playlist, in order. Asserts the `204` on the way through."""
    playlist_id = await a_new_playlist(client)
    answered = await add(client, playlist_id, ids)
    assert answered.status_code == 204, answered.content
    assert answered.content == b""
    return await entries(client, playlist_id)


async def test_ac7_an_album_expands_to_its_tracks_in_the_albums_own_order(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """AC-7's first half, and the half the whole feature was told to get right.

    The album's own order is the order `/Items?parentId=` gives, on both servers: measured
    position by position against a nineteen-track album, and the container itself is never an
    entry `[probe: tools/probe_playlist_expansion.py, Jellyfin 10.11.11, 2026-09-01]`.
    """
    landed = await added(client, [world.album])
    assert landed == list(world.tracks)
    assert world.album not in landed


@pytest.mark.parametrize(
    "container",
    ["album", "series", "season", "artist", "library-root", "playlist", "empty-playlist"],
)
async def test_ac7_every_container_expands_and_two_of_them_were_never_named(
    client: httpx.AsyncClient, world: QueryWorld, container: str
) -> None:
    """ "Every container expands" is a predicate, and the specification had named five kinds.

    Measured, a plain folder, **the library root itself** and **another playlist** expand too, by
    the same rule and through the same branch: anything that is not one of the three types a file
    produces is something a client can ask to add whole
    `[probe: tools/probe_playlist_expansion.py, Jellyfin 10.11.11, 2026-09-01]`. A rule written
    from the five kinds the spec listed would have put a whole library in a playlist as one row.

    The empty container is the other end of the same rule: nothing to add, and the same `204` as a
    container that added forty tracks.
    """
    series = world.series[0]
    named, expected = {
        "album": (world.album, list(world.tracks)),
        "series": (series.id, list(series.episodes)),
        "season": (series.seasons[0], None),
        "artist": (world.album_artist, None),
        "library-root": (identity.for_library(world.music.id), None),
        "playlist": (world.public_playlist.id, list(world.public_playlist.entries)),
        "empty-playlist": (await a_new_playlist(client), []),
    }[container]

    landed = await added(client, [named])
    assert named not in landed, "the container itself is never an entry"
    if expected is not None:
        assert landed == expected
        return

    if container == "season":
        # A season's episodes are a contiguous run of the series' own order, and which run is a
        # fact about the fixture rather than about the rule under test.
        assert landed, "a season with episodes must expand to them"
        assert set(landed) <= set(series.episodes)
        assert landed == [one for one in series.episodes if one in set(landed)]
    elif container == "artist":
        # The **link**, not the tree: an artist's expansion carries the tracks they are credited
        # on, which is why the reference's forty-two rows were forty by a tree walk. And it is
        # grouped by album, which is the middle key of the ordering the reference states.
        assert world.guest_track in landed
        assert set(world.tracks) <= set(landed)
        first = landed.index(world.tracks[0])
        assert landed[first : first + len(world.tracks)] == list(world.tracks)
    else:
        assert set(landed) == set(world.tracks) | {world.guest_track}


async def test_the_expansion_lands_where_the_container_was_named(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """In place, not at the end - which no single-id request can tell apart.

    Measured with a film, an album and a second film: twenty-one entries with the album's
    nineteen between the two films `[probe: tools/probe_playlist_expansion.py, Jellyfin 10.11.11,
    2026-09-01]`.
    """
    first, second = world.corpus[0], world.corpus[1]
    landed = await added(client, [first, world.album, second])
    assert landed == [first, *world.tracks, second]


async def test_ac5_a_repeat_adds_nothing_and_moves_nothing_expansions_included(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """AC-5, on the add path, and once more through a container.

    The entry already there keeps its position - measured on a playlist holding several, because
    a one-entry playlist cannot tell "dropped" from "removed and appended" (T7). Atrium
    de-duplicates **every time**, where the reference manages it only when its own id cache is
    warm (009 spec section 3.4, behaviours section 3.18).
    """
    playlist_id = await a_new_playlist(client)
    await add(client, playlist_id, [world.corpus[0], world.corpus[1], world.corpus[2]])
    before = await entries(client, playlist_id)

    assert (await add(client, playlist_id, [world.corpus[0]])).status_code == 204
    assert await entries(client, playlist_id) == before

    assert (await add(client, playlist_id, [world.corpus[3], world.corpus[3]])).status_code == 204
    assert await entries(client, playlist_id) == [*before, world.corpus[3]]

    # And the same rule through an expansion: the album twice is its tracks once, and a track the
    # album already contributed is not added a second time by naming it directly.
    both = await added(client, [world.album, world.album])
    assert both == list(world.tracks)
    mixed = await added(client, [world.album, world.tracks[1]])
    assert mixed == list(world.tracks)


@pytest.mark.parametrize("order", ["first", "last", "between"])
async def test_an_unknown_id_is_skipped_wherever_it_sits(
    client: httpx.AsyncClient, world: QueryWorld, order: str
) -> None:
    """009 spec section 3.4's "unconditionally here, unlike creation", measured at last.

    The same pair on `POST /Playlists` answers `400` in one order and `200` in the other, because
    creation walks the list to infer a media type. This route infers nothing, so position does not
    matter `[probe: tools/probe_playlist_add_remove.py, Jellyfin 10.11.11, 2026-09-01]`.
    """
    wanted = {
        "first": [ABSENT_ID, world.corpus[0]],
        "last": [world.corpus[0], ABSENT_ID],
        "between": [world.corpus[0], ABSENT_ID, world.corpus[1]],
    }[order]
    expected = [one for one in wanted if one != ABSENT_ID]
    assert await added(client, wanted) == expected


async def test_the_all_zeros_identifier_is_refused_by_both_paths(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """The finding: one identifier is neither skipped nor malformed.

    An all-zeros id is refused with the bare-text `400` on the add route wherever it sits - beside
    a resolvable id included - and on creation **after** the media type has settled, which is
    exactly the position where an ordinary unknown id is skipped. The reference rejects an empty
    GUID in its item lookup rather than missing it, so one guard covers both routes
    `[probe: tools/probe_playlist_add_remove.py, Jellyfin 10.11.11, 2026-09-01]`.

    Nothing lands: the refusal happens before the playlist is written to.
    """
    playlist_id = await a_new_playlist(client)
    for wanted in ([EMPTY_GUID], [world.corpus[0], EMPTY_GUID]):
        answered = await add(client, playlist_id, wanted)
        assert answered.status_code == 400, answered.content
        assert answered.content == CONTROLLER_BODY
        assert answered.headers["content-type"] == "text/plain"
    assert await entries(client, playlist_id) == []

    refused = await client.post(
        "/Playlists", json={"Name": "zeros", "Ids": [world.corpus[0], EMPTY_GUID]}
    )
    assert refused.status_code == 400, refused.content
    assert refused.content == CONTROLLER_BODY

    # The contrast, on the same request shape: an ordinary unknown id in that position is skipped.
    allowed = await client.post(
        "/Playlists", json={"Name": "absent", "Ids": [world.corpus[0], ABSENT_ID]}
    )
    assert allowed.status_code == 200, allowed.content


async def test_ac6_removing_by_entry_id_removes_exactly_that_row(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """AC-6's first half, and the order closes up behind it."""
    playlist_id = await a_new_playlist(client)
    await add(client, playlist_id, list(world.corpus[:4]))

    answered = await drop(client, playlist_id, [world.corpus[1]])
    assert answered.status_code == 204, answered.content
    assert answered.content == b""
    assert await entries(client, playlist_id) == [world.corpus[0], world.corpus[2], world.corpus[3]]

    assert (await drop(client, playlist_id, [world.corpus[0], world.corpus[3]])).status_code == 204
    assert await entries(client, playlist_id) == [world.corpus[2]]


@pytest.mark.parametrize("named", ["absent", "malformed", "all-zeros", "nothing at all"])
async def test_ac6_a_removal_that_names_nothing_present_is_still_204(
    client: httpx.AsyncClient, world: QueryWorld, named: str
) -> None:
    """AC-6's second half, over every class of identifier a client can send.

    Clients retry, and a retry after a removal that worked must not fail (009 spec section 3.5).
    The all-zeros id is the row worth having: it is a `400` on the add route and a `204` here,
    because nothing on this route looks an item up
    `[probe: tools/probe_playlist_add_remove.py, Jellyfin 10.11.11, 2026-09-01]`.
    """
    playlist_id = await a_new_playlist(client)
    await add(client, playlist_id, list(world.corpus[:3]))
    before = await entries(client, playlist_id)

    wanted = {
        "absent": [ABSENT_ID],
        "malformed": ["not-an-identifier"],
        "all-zeros": [EMPTY_GUID],
        "nothing at all": None,
    }[named]
    answered = await drop(client, playlist_id, wanted)
    assert answered.status_code == 204, answered.content
    assert await entries(client, playlist_id) == before


@pytest.mark.parametrize("method", ["POST", "DELETE"])
@pytest.mark.parametrize("case", ["absent", "not-a-playlist", "private-to-this-caller"])
async def test_both_write_routes_answer_the_reads_twenty_byte_refusal(
    client: httpx.AsyncClient, harness: Harness, world: QueryWorld, method: str, case: str
) -> None:
    """T9's fourth shape, measured on the two write routes as well.

    An absent playlist and a real item that is not a playlist are one body on both routes, and a
    playlist this caller may not see is the same body again - so no write can be used to learn
    that a private playlist exists `[probe: tools/probe_playlist_add_remove.py, Jellyfin 10.11.11,
    2026-09-01]`.
    """
    if case == "absent":
        target = ABSENT_ID
    elif case == "not-a-playlist":
        target = world.private_playlist.entries[0]
    else:
        target = world.private_playlist.id
        as_user(harness, world.restricted)

    answered = await client.request(
        method, f"/Playlists/{target}/Items", params={"ids": world.corpus[0]}
    )
    assert answered.status_code == 404, answered.content
    assert answered.content == b'"Playlist not found"'
    assert answered.headers["content-type"] == "application/json; charset=utf-8"


@pytest.mark.parametrize("method", ["POST", "DELETE"])
async def test_a_malformed_playlist_id_is_the_binders_400_on_both_write_routes(
    client: httpx.AsyncClient, method: str
) -> None:
    """One path, two routes, and the reference answers them differently.

    The add binds `playlistId` as an identifier and answers the validation `400`; the **removal**
    binds it as a string it parses itself, so an unparseable one is an unhandled `500` in the
    bare-text shape `[probe: tools/probe_playlist_add_remove.py, Jellyfin 10.11.11, 2026-09-01]`.
    Atrium answers the validation `400` on both - behaviours section 3.19's argument, applied to a
    third request the reference cannot serve.
    """
    answered = await client.request(method, "/Playlists/not-an-identifier/Items")
    assert answered.status_code == 400, answered.content
    assert validation_body(answered) == problem(
        {"playlistId": ["The value 'not-an-identifier' is not valid."]}
    )


@pytest.mark.parametrize("refused", ["read-only share", "public reader", "administrator"])
async def test_ac13_and_ac14_the_edit_refusal_is_the_other_403(
    client: httpx.AsyncClient, harness: Harness, world: QueryWorld, refused: str
) -> None:
    """AC-13 and AC-14: `403` with **no body and no content type**, which is the other shape.

    Measured on the two classes that had never been produced before T5 - a share stored without
    `CanEdit`, and a public playlist's reader - and it is the body-less shape because the
    reference *returns* this refusal where it *throws* the one AC-19 asserts
    `[probe: tools/probe_playlist_shares.py, Jellyfin 10.11.11, 2026-08-31]`.

    The administrator row is the same shape and needs a playlist they can **see**: on a private
    one they are answered `404` by the line above, which is the test below.
    """
    playlist_id, user = {
        "read-only share": (world.read_only_playlist.id, world.restricted),
        "public reader": (world.public_playlist.id, world.restricted),
        "administrator": (world.public_playlist.id, harness.admin),
    }[refused]
    as_user(harness, user)

    for answered in (
        await add(client, playlist_id, [world.corpus[0]]),
        await drop(client, playlist_id, [world.corpus[0]]),
    ):
        assert answered.status_code == 403, answered.content
        assert answered.content == b""
        assert "content-type" not in answered.headers


async def test_a_share_with_can_edit_may_write(
    client: httpx.AsyncClient, harness: Harness, world: QueryWorld
) -> None:
    """AC-14's first half. The share is a real writer, not a reader with a flag."""
    as_user(harness, world.restricted)
    playlist = world.shared_playlist
    assert (await add(client, playlist.id, [world.corpus[0]])).status_code == 204
    assert await entries(client, playlist.id) == [*playlist.entries, world.corpus[0]]
    assert (await drop(client, playlist.id, [world.corpus[0]])).status_code == 204
    assert await entries(client, playlist.id) == list(playlist.entries)


async def test_an_administrator_is_answered_404_before_the_edit_refusal(
    client: httpx.AsyncClient, harness: Harness, world: QueryWorld
) -> None:
    """Spec section 3.7's last row, on the write routes: the `403` is only reachable when visible.

    The reference's own lookup filters by owner, share and `IsPublic` with no administrator branch
    `[source: Emby.Server.Implementations/Playlists/PlaylistManager.cs:62-78 @ v10.11.11]`, so an
    administrator who is none of the three classes never reaches the editing test on a private
    playlist. AC-13's `403` therefore belongs to the playlists they can see, and this is the line
    that says which is which.
    """
    as_user(harness, harness.admin)
    answered = await add(client, world.private_playlist.id, [world.corpus[0]])
    assert answered.status_code == 404, answered.content
    assert answered.content == b'"Playlist not found"'


async def test_ac19_naming_another_user_on_the_add_route_is_the_twenty_five_bytes(
    client: httpx.AsyncClient, harness: Harness, world: QueryWorld
) -> None:
    """AC-19 on the route the reference itself refuses, where the read beside it does not.

    `effective_user`, unchanged: the `403` a non-administrator gets for naming somebody else is
    the controller's own 25 bytes, and the administrator's `userId` is honoured
    `[probe: tools/probe_playlist_visibility.py, Jellyfin 10.11.11, 2026-08-31]`.
    """
    as_user(harness, world.restricted)
    answered = await add(
        client, world.shared_playlist.id, [world.corpus[0]], userId=world.everyone.id
    )
    assert answered.status_code == 403
    assert answered.content == CONTROLLER_BODY
    assert answered.headers["content-type"] == "text/plain"

    as_user(harness, harness.admin)
    allowed = await add(
        client, world.shared_playlist.id, [world.corpus[1]], userId=world.everyone.id
    )
    assert allowed.status_code == 204, allowed.content


async def test_the_two_write_routes_declare_the_references_parameters_and_no_others(
    app: FastAPI,
) -> None:
    """The add takes `userId` and the removal does not, which is the reference's own asymmetry.

    Asserted against the generated document for AC-8's reason: a parameter is discovered there,
    and a `userId` on the removal would be a lever no reference server has `[spec:
    RemoveItemFromPlaylist]`.
    """
    operations = app.openapi()["paths"]["/Playlists/{playlistId}/Items"]
    assert {one["name"] for one in operations["post"]["parameters"] if one["in"] == "query"} == {
        "ids",
        "userId",
    }
    assert {one["name"] for one in operations["delete"]["parameters"] if one["in"] == "query"} == {
        "entryIds"
    }


@pytest.mark.parametrize(
    ("named", "media_type"),
    [("album", "Audio"), ("series", "Video")],
)
async def test_creation_expands_too_and_the_media_type_follows_the_expansion(
    client: httpx.AsyncClient, world: QueryWorld, named: str, media_type: str
) -> None:
    """The other half of plan section 6.2's one function, and T8's named gap closed.

    A container in `Ids` expands on creation exactly as it does on the add route, and the media
    type is settled from what it expanded to: a **series** creates a `Video` playlist where the
    series' own media type is `Unknown` and the empty-list fallback is `Audio`
    `[probe: tools/probe_playlist_expansion.py, Jellyfin 10.11.11, 2026-09-01]`. Reading the
    container's own value would have stored `Unknown`, which creation cannot produce on the
    reference at all (009 spec section 4).
    """
    container = world.album if named == "album" else world.series[0].id
    expected = list(world.tracks) if named == "album" else list(world.series[0].episodes)

    playlist_id = await created_id(
        await client.post("/Playlists", json={"Name": named, "Ids": [container]})
    )
    assert await entries(client, playlist_id) == expected
    assert (await item(client, playlist_id))["MediaType"] == media_type


async def test_a_video_genre_settles_video_and_expands_to_nothing(
    client: httpx.AsyncClient,
) -> None:
    """The one media type no expansion can produce, and the only branch that answers it.

    The reference names four containers that settle a media type by their **kind**, before their
    contents are looked at: three music ones answer `Audio` and a `Genre` answers `Video`
    `[source: Emby.Server.Implementations/Playlists/PlaylistManager.cs:95-114 @ v10.11.11]`. The
    row exists because a genre's *expansion* is empty - the folder branch looks for children, and
    a by-name row has none `[source: MediaBrowser.Controller/Playlists/Playlist.cs:217-229 @
    v10.11.11]` - so nothing downstream could ever settle it. Both halves are asserted here, on
    the by-name row two films share.

    Unmeasurable against the reference used by this project: it holds no genre rows at all, which
    is why this is the one rule in T10 carried by a source citation rather than by a probe.
    """
    listed = await client.get("/Items", params={"includeItemTypes": "Genre", "recursive": "true"})
    assert listed.status_code == 200, listed.content
    genre = json.loads(listed.content)["Items"][0]["Id"]

    playlist_id = await created_id(
        await client.post("/Playlists", json={"Name": "by genre", "Ids": [genre]})
    )
    assert await entries(client, playlist_id) == []
    assert (await item(client, playlist_id))["MediaType"] == "Video"


# --------------------------------------------------------------------------------------------
# `POST /Playlists/{playlistId}/Items/{itemId}/Move/{newIndex}` - the move (T11)
# --------------------------------------------------------------------------------------------
#
# Every row below is a transcription of a measured run, not a derivation of the model the domain
# implements `[probe: tools/probe_playlist_move.py, Jellyfin 10.11.11, 2026-09-01]`. The matrix is
# thirty pairs because spec section 6 asks for it as a test and because the model it checks was
# once derived from a single measured pair.

#: The five sources moved to each of the six targets, as the reference answered them, with the
#: entries labelled `A`..`E` in stored order. Thirty rows, all `204`.
MEASURED_MATRIX = {
    "A": ("ABCDE", "BACDE", "BCADE", "BCDAE", "BCDEA", "BCDEA"),
    "B": ("BACDE", "ABCDE", "ACBDE", "ACDBE", "ACDEB", "ACDEB"),
    "C": ("CABDE", "ACBDE", "ABCDE", "ABDCE", "ABDEC", "ABDEC"),
    "D": ("DABCE", "ADBCE", "ABDCE", "ABCDE", "ABCED", "ABCED"),
    "E": ("EABCD", "AEBCD", "ABECD", "ABCED", "ABCDE", "ABCDE"),
}

LABELS = "ABCDE"


def dashed(identifier: str) -> str:
    """The other spelling of one identifier - accepted on one segment of this path and not both."""
    parts = (
        identifier[:8],
        identifier[8:12],
        identifier[12:16],
        identifier[16:20],
        identifier[20:],
    )
    return "-".join(parts)


async def move(
    client: httpx.AsyncClient, playlist_id: str, entry: str, new_index: int | str
) -> httpx.Response:
    return await client.post(f"/Playlists/{playlist_id}/Items/{entry}/Move/{new_index}")


async def five_entries(client: httpx.AsyncClient, world: QueryWorld) -> str:
    """A fresh five-entry playlist, one per case: a case asking *did anything move* cannot share."""
    named = list(world.corpus[0:5])
    playlist_id = await created_id(
        await client.post("/Playlists", json={"Name": "T11", "Ids": named})
    )
    assert await entries(client, playlist_id) == named
    return playlist_id


@pytest.mark.parametrize("source", list(LABELS))
async def test_ac9_the_thirty_measured_pairs_over_http(
    client: httpx.AsyncClient, world: QueryWorld, source: str
) -> None:
    """AC-9, and the matrix spec section 6 asks for - at the boundary, one fresh playlist a pair.

    T1 proved the arithmetic against these same thirty answers; this proves the **route** reaches
    it, which is a different claim: a route that read the stored order where it should read the
    caller's, or judged the index after the entry, passes every unit test the domain has.

    `0 -> 3` giving `B C D A E` is one row of it, and the row a client author can get wrong
    without noticing - every upward move agrees under both readings
    `[probe: tools/probe_playlist_move.py, Jellyfin 10.11.11, 2026-09-01]`.
    """
    for target, expected in enumerate(MEASURED_MATRIX[source]):
        playlist_id = await five_entries(client, world)
        named = await entries(client, playlist_id)
        labelled = dict(zip(LABELS, named, strict=True))

        answered = await move(client, playlist_id, labelled[source], target)
        assert answered.status_code == 204, answered.content
        assert answered.content == b""

        landed = await entries(client, playlist_id)
        assert landed == [labelled[one] for one in expected], f"{source} -> {target}"
        assert set(landed) == set(named), "a move reissues no entry id (AC-9)"


@pytest.mark.parametrize(
    ("case", "new_index", "entry", "status"),
    [
        ("the last index", 4, "own", 204),
        ("one past the end, which is the clamp", 5, "own", 204),
        ("two past the end", 6, "own", 400),
        ("negative", -1, "own", 400),
        ("where it already is", 0, "own", 204),
        ("an absent entry, index in range", 1, ABSENT_ID, 204),
        ("an absent entry, index past the end", 6, ABSENT_ID, 400),
        ("the all-zeros entry, index in range", 1, EMPTY_GUID, 204),
        ("the all-zeros entry, index past the end", 6, EMPTY_GUID, 400),
        ("a malformed entry, index in range", 1, "not-an-identifier", 204),
        ("a malformed entry, index past the end", 6, "not-an-identifier", 400),
    ],
)
async def test_ac10_and_ac11_every_row_of_the_boundary_table(
    client: httpx.AsyncClient,
    world: QueryWorld,
    case: str,
    new_index: int,
    entry: str,
    status: int,
) -> None:
    """Spec section 3.5's third column, row by row, and the table it replaced had one row right.

    The clamp is exactly **one** position wide: index 5 on a five-entry playlist puts the entry
    last and index 6 is the reference's `500`, which Atrium answers `400` (behaviours section
    3.15). A negative index moves the entry to position 1 there and moves nothing here. An entry
    id that is not in the playlist is a silent `204` with the index in range and the refusal with
    it out of range, because the index is judged **before** the entry is looked up - parity, and
    the row the specification had wrong for the longest.

    The all-zeros identifier is **not** the refusal it is on the add route, and the malformed one
    is not the binder's `400`: neither segment is parsed here, so both are simply entries this
    playlist does not hold `[probe: tools/probe_playlist_move.py, Jellyfin 10.11.11, 2026-09-01]`.
    """
    playlist_id = await five_entries(client, world)
    before = await entries(client, playlist_id)
    addressed = before[0] if entry == "own" else entry

    answered = await move(client, playlist_id, addressed, new_index)
    assert answered.status_code == status, answered.content

    if status == 400:
        assert answered.content == CONTROLLER_BODY
        assert answered.headers["content-type"] == "text/plain"
        assert await entries(client, playlist_id) == before, "a refused move moves nothing"
        return

    landed = await entries(client, playlist_id)
    assert set(landed) == set(before)
    if entry != "own":
        assert landed == before, "an entry the playlist does not hold changes nothing"
    elif new_index == 0:
        assert landed == before, "moving an entry where it already is changes nothing"
    else:
        assert landed == [*before[1:], before[0]], "the clamp puts the entry last"


@pytest.mark.parametrize(
    ("spelling", "moves"),
    [("canonical", True), ("upper-case", True), ("dashed", False), ("braced", False)],
)
async def test_the_entry_segment_is_matched_as_text_and_not_parsed(
    client: httpx.AsyncClient, world: QueryWorld, spelling: str, moves: bool
) -> None:
    """The finding this task turned on: `itemId` is **not** an identifier on this route.

    The reference compares it against the 32-hex spelling of each entry, case-insensitively, and
    parses nothing `[source: Emby.Server.Implementations/Playlists/PlaylistManager.cs:308-323 @
    v10.11.11]` - so an upper-case id moves the entry and a **dashed** one, which every other
    route in this feature accepts, moves nothing at all
    `[probe: tools/probe_playlist_move.py, Jellyfin 10.11.11, 2026-09-01]`. Normalising it the way
    the add route normalises its list would reorder a playlist no reference server reorders, and
    the caller would see it in the order that comes back.
    """
    playlist_id = await five_entries(client, world)
    before = await entries(client, playlist_id)
    addressed = {
        "canonical": before[0],
        "upper-case": before[0].upper(),
        "dashed": dashed(before[0]),
        "braced": "{" + before[0] + "}",
    }[spelling]

    answered = await move(client, playlist_id, addressed, 1)
    assert answered.status_code == 204, answered.content
    landed = await entries(client, playlist_id)
    assert landed == ([before[1], before[0], *before[2:]] if moves else before)


async def test_the_playlist_segment_is_parsed_where_the_entry_segment_is_not(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """One path, two identifier segments, two spellings of one value - and both are measured.

    A dashed **playlist** id addresses the playlist, because the reference hands that segment to
    the framework's parser `[probe: tools/probe_playlist_move.py, Jellyfin 10.11.11, 2026-09-01]`.
    That asymmetry is the whole reason `playlistId` is a `WireGuid` here and `itemId` is a string.
    """
    playlist_id = await five_entries(client, world)
    before = await entries(client, playlist_id)

    answered = await move(client, dashed(playlist_id), before[0], 1)
    assert answered.status_code == 204, answered.content
    assert await entries(client, playlist_id) == [before[1], before[0], *before[2:]]


async def test_a_malformed_playlist_id_is_the_binders_400_here_too(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """The fourth request of behaviours section 3.19, on the third route to have one.

    This route parses `playlistId` inside the action as the **removal** does, not as the addition
    does, so a malformed one is an unhandled `500` in the bare-text shape
    `[probe: tools/probe_playlist_move.py, Jellyfin 10.11.11, 2026-09-01]`
    `[source: Jellyfin.Api/Controllers/PlaylistsController.cs:409-431 @ v10.11.11]`. Atrium
    answers the validation `400` on all three write routes: one shape for one path.
    """
    answered = await move(client, "not-an-identifier", world.corpus[0], 1)
    assert answered.status_code == 400, answered.content
    assert validation_body(answered) == problem(
        {"playlistId": ["The value 'not-an-identifier' is not valid."]}
    )


async def test_a_new_index_that_is_not_a_number_is_the_binders_400_and_that_is_parity(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """The one refusal on this route that needs no code, and it is keyed by the path parameter.

    Measured as the 261-byte problem-details document keyed `newIndex`, which is T9's path-binder
    shape and not the body's `The supplied value is invalid.`
    `[probe: tools/probe_playlist_move.py, Jellyfin 10.11.11, 2026-09-01]`.
    """
    playlist_id = await five_entries(client, world)
    before = await entries(client, playlist_id)

    answered = await move(client, playlist_id, before[0], "banana")
    assert answered.status_code == 400, answered.content
    assert validation_body(answered) == problem({"newIndex": ["The value 'banana' is not valid."]})
    assert await entries(client, playlist_id) == before


@pytest.mark.parametrize("case", ["absent", "not-a-playlist", "invisible"])
async def test_the_move_answers_the_twenty_bytes_before_anything_else(
    client: httpx.AsyncClient, harness: Harness, world: QueryWorld, case: str
) -> None:
    """T9's fourth shape on the third write route, and it is reached before the index is judged."""
    if case == "absent":
        target = ABSENT_ID
    elif case == "not-a-playlist":
        target = world.private_playlist.entries[0]
    else:
        target = world.private_playlist.id
        as_user(harness, world.restricted)

    answered = await move(client, target, world.corpus[0], 99)
    assert answered.status_code == 404, answered.content
    assert answered.content == b'"Playlist not found"'
    assert answered.headers["content-type"] == "application/json; charset=utf-8"


@pytest.mark.parametrize("refused", ["read-only share", "public reader", "administrator"])
@pytest.mark.parametrize("new_index", [1, 99])
async def test_ac13_and_ac14_the_move_refusal_is_the_body_less_403(
    client: httpx.AsyncClient,
    harness: Harness,
    world: QueryWorld,
    refused: str,
    new_index: int,
) -> None:
    """AC-13 and AC-14 on the route they were written for, and the order is measured.

    **The caller is judged before the index**, which is not deducible from the arithmetic: a
    shared reader without `CanEdit` moving to an index the reference crashes on is answered `403`
    and not `500` `[probe: tools/probe_playlist_shares.py, Jellyfin 10.11.11, 2026-09-01]`. So
    `99` and `1` are the same refusal here, and the `400` this route makes its own is only
    reachable by a caller who may edit.
    """
    playlist, user = {
        "read-only share": (world.read_only_playlist, world.restricted),
        "public reader": (world.public_playlist, world.restricted),
        "administrator": (world.public_playlist, harness.admin),
    }[refused]
    as_user(harness, user)

    # The entry comes from the fixture rather than from a read: the public playlist holds the
    # three tracks and `restricted` cannot open the music library, so that reader is shown an
    # empty playlist (T9's finding) - and the refusal below happens before any entry is looked up.
    answered = await move(client, playlist.id, playlist.entries[0], new_index)
    assert answered.status_code == 403, answered.content
    assert answered.content == b""
    assert "content-type" not in answered.headers


async def test_ac17_a_readers_move_indexes_the_list_that_reader_was_given(
    client: httpx.AsyncClient, harness: Harness, world: QueryWorld
) -> None:
    """AC-17's second half, and this feature's one rule with no reference answer behind it.

    The reference indexes the entries the caller can see and then inserts at the neighbour's
    position in the order *before* the entry was removed, so a downward move by a reader who is
    shown less than the whole lands one position short of where they asked - and it will reorder
    an entry that reader was never shown. Neither is reachable against a reference server, because
    what it hides is hidden by a parental-rating check and never by library access (behaviours
    section 3.17), so Atrium's rule is argued from that divergence rather than transcribed: the
    entry lands at `newIndex` **of the list the reader was given**.
    """
    playlist = world.cross_library_playlist
    seen = list(playlist.restricted_sees)
    as_user(harness, world.restricted)

    answered = await move(client, playlist.id, seen[0], 1)
    assert answered.status_code == 204, answered.content
    assert await entries(client, playlist.id) == [seen[1], seen[0], seen[2]]

    as_user(harness, world.everyone)
    stored = await entries(client, playlist.id)
    assert stored == [playlist.entries[1], seen[1], seen[0], seen[2], playlist.entries[4]]
    assert set(stored) == set(playlist.entries), "no entry the reader cannot see is reissued"


async def test_ac17_an_entry_the_reader_cannot_see_is_answered_as_an_absent_one(
    client: httpx.AsyncClient, harness: Harness, world: QueryWorld
) -> None:
    """The other half of the same rule: `204`, and nothing changes.

    The reference moves it, because the list it looks the entry up in is not the list it bounded
    the index against. Under behaviours section 3.17 that entry is one this reader was never
    shown, so no client can have been built on reordering it.
    """
    playlist = world.cross_library_playlist
    hidden = playlist.beyond_restricted[0]
    as_user(harness, world.restricted)

    # Index 3 and not 1: the hidden entry is *stored* at index 1, so a route that indexed the
    # stored order would answer this case with a no-op and the test would pass for the wrong
    # reason. It is the last index this reader may name, and it moves the entry under any reading
    # that reaches it at all.
    answered = await move(client, playlist.id, hidden, 3)
    assert answered.status_code == 204, answered.content

    as_user(harness, world.everyone)
    assert await entries(client, playlist.id) == list(playlist.entries)


async def test_a_readers_index_is_bounded_by_what_that_reader_was_given(
    client: httpx.AsyncClient, harness: Harness, world: QueryWorld
) -> None:
    """The bound moves with the view, which is the half of the rule that **is** parity.

    The reference bounds `newIndex` against the accessible children too, which is why one past
    that count is the last position and two past it is its `500`. Three visible entries of five:
    index 3 is the clamp and index 4 is the refusal.
    """
    playlist = world.cross_library_playlist
    seen = list(playlist.restricted_sees)
    as_user(harness, world.restricted)

    assert (await move(client, playlist.id, seen[0], len(seen))).status_code == 204
    assert await entries(client, playlist.id) == [*seen[1:], seen[0]]

    refused = await move(client, playlist.id, seen[0], len(seen) + 1)
    assert refused.status_code == 400, refused.content
    assert refused.content == CONTROLLER_BODY
    assert refused.headers["content-type"] == "text/plain"


async def test_the_move_route_declares_the_references_parameters_and_no_others(
    app: FastAPI,
) -> None:
    """No `userId`, which is the reference's own shape rather than an omission `[spec: MoveItem]`.

    Asserted against the generated document for AC-8's reason: a parameter is discovered there,
    and one this route does not have would be a lever no reference server offers.
    """
    operation = app.openapi()["paths"]["/Playlists/{playlistId}/Items/{itemId}/Move/{newIndex}"]
    parameters = operation["post"]["parameters"]
    assert [one["name"] for one in parameters if one["in"] == "path"] == [
        "playlistId",
        "itemId",
        "newIndex",
    ]
    assert [one["name"] for one in parameters if one["in"] == "query"] == []


# ------------------------------------------------------------------------------------------
# T12 - `DELETE /Items/{itemId}`: three refusals, one of them ours
# ------------------------------------------------------------------------------------------
#
# The route 009 owns half of. Its playlist half is parity down to the bytes; everything else on
# it is refused, which is the one divergence in this project not argued from "no client can tell"
# (behaviours section 4.3). Every cell below was measured before it was written
# `[probe: tools/probe_item_deletion.py, Jellyfin 10.11.11, 2026-09-01]`.

#: The reference's own refusal, byte for byte: the *fourth* error shape at a status this project
#: had only ever sent empty.
UNAUTHORIZED = b'"Unauthorized access"'


async def delete_item(client: httpx.AsyncClient, item_id: str) -> httpx.Response:
    return await client.delete(f"/Items/{item_id}")


async def test_ac12_the_owner_deletes_their_playlist_and_it_is_gone(
    client: httpx.AsyncClient, harness: Harness, world: QueryWorld
) -> None:
    """AC-12's first clause, and the success shape beside it: `204`, no body, no content type."""
    as_user(harness, world.everyone)
    playlist = world.private_playlist

    answered = await delete_item(client, playlist.id)
    assert answered.status_code == 204, answered.content
    assert answered.content == b""
    assert "content-type" not in answered.headers

    assert (await client.get(f"/Items/{playlist.id}")).status_code == 404
    assert (await client.get(f"/Playlists/{playlist.id}/Items")).status_code == 404
    listed = await client.get(
        "/Items", params={"includeItemTypes": "Playlist", "recursive": "true", "limit": "1000"}
    )
    assert playlist.id not in {row["Id"] for row in listed.json()["Items"]}


async def test_deleting_a_playlist_takes_its_entries_and_its_shares_with_it(
    client: httpx.AsyncClient, harness: Harness, world: QueryWorld
) -> None:
    """The cascades, asserted where they are observable: the share is gone because the user it
    was granted to can no longer reach the playlist, and the entries are gone because the id
    answers nothing at all.

    A fresh playlist rather than a seeded one, so the assertion is about this deletion and not
    about what the world happened to hold."""
    as_user(harness, world.everyone)
    playlist_id = await created_id(
        await client.post(
            "/Playlists",
            json={
                "Name": "T12",
                "Ids": list(world.corpus[0:2]),
                "Users": [{"UserId": world.restricted.id, "CanEdit": True}],
            },
        )
    )
    as_user(harness, world.restricted)
    assert (await client.get(f"/Playlists/{playlist_id}/Items")).status_code == 200

    as_user(harness, world.everyone)
    assert (await delete_item(client, playlist_id)).status_code == 204

    as_user(harness, world.restricted)
    assert (await client.get(f"/Playlists/{playlist_id}/Items")).status_code == 404
    as_user(harness, world.everyone)
    assert (await client.get(f"/Items/{playlist_id}")).status_code == 404
    # The films are untouched: a cascade that reached the items would be a deletion of media
    # through a route that refuses to delete media.
    for item_id in world.corpus[0:2]:
        assert (await client.get(f"/Items/{item_id}")).status_code == 200


async def test_ac13_an_administrator_deletes_a_playlist_they_neither_own_nor_may_read(
    client: httpx.AsyncClient, harness: Harness, world: QueryWorld
) -> None:
    """AC-13's deletion half, and the row spec section 3.7 asserts: deletion is the **one**
    operation an administrator may perform on a playlist that is none of theirs.

    **And unlike the editing refusal, it is not conditional on seeing the playlist.** T10 had to
    correct AC-13 because the editing routes go through a lookup that filters by owner, share and
    `IsPublic`; this route goes through no such lookup, measured - the same administrator is
    answered `404` by `GET /Items/{id}` and `204` here, in the same private playlist, in the same
    test `[probe: tools/probe_item_deletion.py, Jellyfin 10.11.11, 2026-09-01]`.
    """
    as_user(harness, harness.admin)
    playlist = world.private_playlist
    assert (await client.get(f"/Items/{playlist.id}")).status_code == 404
    assert (await client.get(f"/Playlists/{playlist.id}/Items")).status_code == 404

    assert (await delete_item(client, playlist.id)).status_code == 204

    as_user(harness, world.everyone)
    assert (await client.get(f"/Items/{playlist.id}")).status_code == 404


@pytest.mark.parametrize(
    "refused", ["share with can_edit", "share without can_edit", "public reader", "stranger"]
)
async def test_ac12_a_caller_who_may_not_delete_is_the_401_with_its_body(
    client: httpx.AsyncClient, harness: Harness, world: QueryWorld, refused: str
) -> None:
    """AC-12's third clause: `401`, and the body is the *fourth* shape rather than an empty one.

    Four classes reach it and none of them is an administrator: a share **with** `CanEdit` may
    reorder the playlist and may not delete it, which is the asymmetry the three permission
    functions exist to carry (009 spec section 3.7). Measured with its content type, because a
    `401` in this project had never carried a body before
    `[probe: tools/probe_item_deletion.py, Jellyfin 10.11.11, 2026-09-01]`.
    """
    playlist_id = {
        "share with can_edit": world.shared_playlist.id,
        "share without can_edit": world.read_only_playlist.id,
        "public reader": world.public_playlist.id,
        "stranger": world.private_playlist.id,
    }[refused]
    as_user(harness, world.restricted)

    answered = await delete_item(client, playlist_id)
    assert answered.status_code == 401, answered.content
    assert answered.content == UNAUTHORIZED
    assert answered.headers["content-type"] == "application/json; charset=utf-8"

    as_user(harness, world.everyone)
    assert (await client.get(f"/Items/{playlist_id}")).status_code == 200


async def test_the_deletion_refusal_discloses_a_playlist_every_other_route_hides(
    client: httpx.AsyncClient, harness: Harness, world: QueryWorld
) -> None:
    """The finding this task turned on, kept as a test rather than as a sentence.

    Spec section 3.6 said `404` for an invisible item, and for a **playlist** that is false: this
    route applies no visibility test at all, so `restricted` - who is answered the read route's
    twenty bytes and the item route's problem details for this same playlist - is answered `401`
    here, and learns that it exists `[probe: tools/probe_item_deletion.py, Jellyfin 10.11.11,
    2026-09-01]`. Replicated rather than corrected: the id has to be known before it can be
    asked about, and a server that answered `404` would differ from the reference on a request a
    client can make.
    """
    as_user(harness, world.restricted)
    private = world.private_playlist.id

    assert (await client.get(f"/Items/{private}")).status_code == 404
    assert (await client.get(f"/Playlists/{private}/Items")).content == b'"Playlist not found"'
    assert (await delete_item(client, private)).status_code == 401

    # And a `404` on this route therefore means what it says: no such item, for anybody.
    assert (await delete_item(client, ABSENT_ID)).status_code == 404


async def test_an_unknown_identifier_is_the_problem_details_404(
    client: httpx.AsyncClient, harness: Harness, world: QueryWorld
) -> None:
    """Not the read route's twenty bytes: this route is `LibraryController`'s and answers the
    problem details every `NotFoundError` in this project answers, measured against a body the
    playlist routes one path away do not send."""
    as_user(harness, world.everyone)
    answered = await delete_item(client, ABSENT_ID)
    assert answered.status_code == 404, answered.content
    body = json.loads(answered.content)
    body.pop("traceId")
    assert body == {
        "type": "https://tools.ietf.org/html/rfc9110#section-15.5.5",
        "title": "Not Found",
        "status": 404,
    }


async def test_a_malformed_identifier_is_the_binders_validation_400(
    client: httpx.AsyncClient, harness: Harness, world: QueryWorld
) -> None:
    """`itemId` is typed as an identifier because the reference binds it as one - the route's
    parameter is a parsed value, so a malformed one never reaches the action and is the
    validation `400` keyed on the path parameter's own spelling. Measured, and not deduced from
    the two routes in this feature that answer otherwise (T11)."""
    as_user(harness, world.everyone)
    answered = await delete_item(client, "not-an-identifier")
    assert answered.status_code == 400, answered.content
    assert validation_body(answered) == problem(
        {"itemId": ["The value 'not-an-identifier' is not valid."]}
    )


async def test_an_all_zeros_identifier_is_the_bare_text_400(
    client: httpx.AsyncClient, harness: Harness, world: QueryWorld
) -> None:
    """`Guid.Empty` is the third class of identifier here too, and it is refused before anything
    is looked up - the same guard T10 found in the reference's own item lookup, on a route no
    document had asked about `[probe: tools/probe_item_deletion.py, Jellyfin 10.11.11,
    2026-09-01]`."""
    as_user(harness, world.everyone)
    answered = await delete_item(client, EMPTY_GUID)
    assert answered.status_code == 400, answered.content
    assert answered.content == CONTROLLER_BODY
    assert answered.headers["content-type"] == "text/plain"


@pytest.mark.parametrize("kind", ["a film", "an album", "a genre"])
async def test_ac12_anything_that_is_not_a_playlist_is_refused(
    client: httpx.AsyncClient, harness: Harness, world: QueryWorld, kind: str
) -> None:
    """AC-12's second clause, widened to what the route actually decides (behaviours section 4.3).

    The rule is *not a playlist*, rather than *a file backs it*: a genre this server rebuilds on
    the next scan would be a deletion that does not stick, which is Principle VI's
    plausible-looking stub. The reference refuses that one too - `CanDelete()` is `IsFileProtocol`
    and a by-name row has no file `[source: MediaBrowser.Controller/Entities/BaseItem.cs:820-828 @
    v10.11.11]` - though with `401` rather than this `403`, which is the divergence and not an
    accident.
    """
    as_user(harness, world.everyone)
    item_id = {"a film": world.corpus[0], "an album": world.album, "a genre": None}[kind]
    if item_id is None:
        genres = await client.get("/Genres", params={"limit": "1"})
        item_id = genres.json()["Items"][0]["Id"]

    answered = await delete_item(client, item_id)
    assert answered.status_code == 403, answered.content
    assert answered.content == CONTROLLER_BODY
    assert answered.headers["content-type"] == "text/plain"
    assert (await client.get(f"/Items/{item_id}")).status_code == 200


async def test_an_item_this_caller_cannot_see_is_404_before_the_refusal(
    client: httpx.AsyncClient, harness: Harness, world: QueryWorld
) -> None:
    """Media is the other way round from a playlist, and measured: an item in a library this
    caller cannot open is `404` on this route, exactly as it is on `/Items/{itemId}` - the
    reference's own lookup filters media by collection folder and filters a playlist by nothing
    `[probe: tools/probe_item_deletion.py, Jellyfin 10.11.11, 2026-09-01]`.

    So the `403` above is a refusal only the callers who can see the item ever meet, and the
    divergence discloses nothing the read routes do not.
    """
    as_user(harness, world.restricted)
    track = world.tracks[0]
    assert (await client.get(f"/Items/{track}")).status_code == 404
    assert (await delete_item(client, track)).status_code == 404


async def test_the_delete_route_declares_the_references_parameters_and_no_others(
    app: FastAPI,
) -> None:
    """No `userId` `[spec: DeleteItem]`: the reference's action reads the caller's own identity,
    so a parameter here would be a way to delete on somebody else's behalf that no reference
    server offers. Asserted against the generated document, where a client discovers one."""
    operation = app.openapi()["paths"]["/Items/{itemId}"]["delete"]
    assert [one["name"] for one in operation["parameters"] if one["in"] == "path"] == ["itemId"]
    assert [one["name"] for one in operation["parameters"] if one["in"] == "query"] == []


async def test_ac12_a_film_is_refused_and_the_file_is_still_on_disk(
    client: httpx.AsyncClient, harness: Harness, world: QueryWorld, tmp_path: Path
) -> None:
    """AC-12's second clause, asserted where the divergence's whole argument lives: the file.

    The seeded world's libraries are rooted at paths that do not exist, so nothing in it can tell
    "the route refused" from "the route deleted the row and there was no file to remove". This
    test roots a fourth library inside `tmp_path`, puts real bytes in it, and asserts them after
    the refusal - which is the only assertion behaviours section 4.3's argument can be made with.
    """
    root = tmp_path / "deletable"
    (root / "A Film").mkdir(parents=True)
    film = root / "A Film" / "A Film.mkv"
    film.write_bytes(b"not really a film")

    with harness.app.state.sessions.begin() as opened:
        library = LibraryRepository(opened).add(
            Library(
                id="c" * 32,
                name="Deletable",
                collection_type=CollectionType.MOVIES,
                roots=(str(root),),
            )
        )
        relative = "A Film/A Film.mkv"
        item = Item(
            id=identity.for_file(ItemType.MOVIE, library.id, relative),
            type=ItemType.MOVIE,
            name="A Film",
            library_id=library.id,
            sources=(MediaSource(relative_path=relative, size=film.stat().st_size, mtime_ns=1),),
        )
        ItemRepository(opened).add(item)

    as_user(harness, world.everyone)
    assert (await client.get(f"/Items/{item.id}")).status_code == 200

    answered = await delete_item(client, item.id)
    assert answered.status_code == 403, answered.content
    assert answered.content == CONTROLLER_BODY
    assert answered.headers["content-type"] == "text/plain"

    assert film.exists()
    assert film.read_bytes() == b"not really a film"
    assert (await client.get(f"/Items/{item.id}")).status_code == 200


# ------------------------------------------------------------------------------------------
# T13 - `POST /Items/{itemId}`: the rename, and the two things it refuses
# ------------------------------------------------------------------------------------------
#
# The other method of the path above, and the one route in v1 an authorization policy guards.
# Every cell was measured before it was written `[probe: tools/probe_playlist_rename.py,
# Jellyfin 10.11.11, 2026-09-01]`, including the two the documents had not asked about: the
# three properties a body may not omit, and the seven the reference applies beside `Name`.

#: The smallest body the reference accepts, and the shape of the finding: `Name` alone is a
#: `400`. `Genres`, `Tags` and `ProviderIds` are required and non-null; the other thirty-five
#: properties of a read may all be left out.
REQUIRED_BESIDE_NAME: dict[str, Any] = {"Genres": [], "Tags": [], "ProviderIds": {}}


def rename_body(name: str | None, **changed: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"Name": name, **REQUIRED_BESIDE_NAME}
    body.update(changed)
    return body


async def rename(client: httpx.AsyncClient, item_id: str, body: dict[str, Any]) -> httpx.Response:
    return await client.post(f"/Items/{item_id}", json=body)


async def test_ac18_an_administrator_renames_a_playlist(
    client: httpx.AsyncClient, harness: Harness, world: QueryWorld
) -> None:
    """AC-18's first half, with the success shape beside it: `204`, no body, no content type.

    The name is asserted where a client reads it - the item route, the listing, and a search -
    because the rename writes three columns and only the first of them is `Name` on the wire. A
    rename that wrote one would leave a playlist sorting under its old name and unfindable by
    `searchTerm`, which is the failure 005 T6 found one table away.
    """
    as_user(harness, harness.admin)
    playlist = world.public_playlist

    answered = await rename(client, playlist.id, rename_body("Renamed By An Administrator"))
    assert answered.status_code == 204, answered.content
    assert answered.content == b""
    assert "content-type" not in answered.headers

    assert (await item(client, playlist.id))["Name"] == "Renamed By An Administrator"
    found = await client.get(
        "/Items",
        params={"searchTerm": "renamed by an", "includeItemTypes": "Playlist", "recursive": "true"},
    )
    assert [row["Id"] for row in found.json()["Items"]] == [playlist.id]


async def test_ac18_the_non_administrator_owner_is_the_empty_403(
    client: httpx.AsyncClient, harness: Harness, world: QueryWorld
) -> None:
    """AC-18's second half, and the scope finding of this whole feature: **the rename the music
    client calls refuses that client's own users**.

    The playlist's own owner is answered `403` with no body and no content type - an
    authorization policy's refusal, decided before the controller runs - which is the *other*
    shape from AC-19's 25 bytes and is asserted apart from it on purpose (T2). The owner's own
    playlist keeps its name, so the refusal is total rather than partial.
    """
    as_user(harness, world.everyone)
    playlist = world.private_playlist
    before = (await item(client, playlist.id))["Name"]

    answered = await rename(client, playlist.id, rename_body("Renamed By Its Owner"))
    assert answered.status_code == 403, answered.content
    assert answered.content == b""
    assert "content-type" not in answered.headers
    assert (await item(client, playlist.id))["Name"] == before


@pytest.mark.parametrize(
    "target", ["their own playlist", "an identifier naming nothing", "not an identifier"]
)
async def test_the_policy_refuses_before_anything_about_the_item_is_read(
    client: httpx.AsyncClient, harness: Harness, world: QueryWorld, target: str
) -> None:
    """The ordering, measured rather than chosen: a non-administrator meets the same empty `403`
    for a well-formed identifier that names nothing and for a path segment that is not an
    identifier at all, where an administrator sending the same two requests is answered `404` and
    the binder's validation `400` `[probe: tools/probe_playlist_rename.py, Jellyfin 10.11.11,
    2026-09-01]`.

    That is what an authorization policy attached to a whole controller does, and it is why the
    test exists: a caller who may not use this route learns nothing from it, not even whether an
    identifier addresses something.
    """
    as_user(harness, world.everyone)
    item_id = {
        "their own playlist": world.private_playlist.id,
        "an identifier naming nothing": ABSENT_ID,
        "not an identifier": "not-an-identifier",
    }[target]

    answered = await rename(client, item_id, rename_body("Refused"))
    assert answered.status_code == 403, answered.content
    assert answered.content == b""
    assert "content-type" not in answered.headers


@pytest.mark.parametrize("omitted", ["Genres", "Tags", "ProviderIds"])
@pytest.mark.parametrize("how", ["absent", "null"])
async def test_the_three_properties_a_body_may_not_omit(
    client: httpx.AsyncClient, harness: Harness, world: QueryWorld, omitted: str, how: str
) -> None:
    """Parity, and the finding the task statement asked for: *"applies `Name` and nothing else"*
    is a claim about a body with thirty-nine properties, and three of them are load-bearing.

    Dropping each property of a whole posted body in turn, the reference refuses exactly
    `Genres`, `Tags` and `ProviderIds` - absent or `null`, identically - with the controller's 25
    bytes at `400`, and accepts a body of those three and a `Name`
    `[probe: tools/probe_playlist_rename.py, Jellyfin 10.11.11, 2026-09-01]`. So the client's
    round trip is load-bearing rather than incidental: a client that posted `{"Name": ...}` alone
    would be refused by a stock reference server too.
    """
    as_user(harness, harness.admin)
    playlist = world.public_playlist
    before = (await item(client, playlist.id))["Name"]

    body = rename_body("Renamed")
    if how == "absent":
        del body[omitted]
    else:
        body[omitted] = None

    answered = await rename(client, playlist.id, body)
    assert answered.status_code == 400, answered.content
    assert answered.content == CONTROLLER_BODY
    assert answered.headers["content-type"] == "text/plain"
    assert (await item(client, playlist.id))["Name"] == before


async def test_a_body_of_exactly_the_four_properties_is_accepted(
    client: httpx.AsyncClient, harness: Harness, world: QueryWorld
) -> None:
    """The rule stated the other way round, because a refusal test alone cannot say where the
    line is: the thirty-five properties a read emits and this body leaves out change nothing."""
    as_user(harness, harness.admin)
    playlist = world.public_playlist

    answered = await rename(client, playlist.id, rename_body("Four Properties"))
    assert answered.status_code == 204, answered.content
    assert (await item(client, playlist.id))["Name"] == "Four Properties"


@pytest.mark.parametrize("how", ["absent", "null"])
async def test_a_body_with_no_name_is_refused_where_the_reference_erases_the_name(
    client: httpx.AsyncClient, harness: Harness, world: QueryWorld, how: str
) -> None:
    """009's sixth divergence, in the same bytes as the row above (behaviours section 3.21).

    Measured: a whole item body whose `Name` is absent, or present and `null`, is answered `204`
    and the playlist's name is **erased** - it comes back with no `Name` property at all
    `[probe: tools/probe_playlist_rename.py, Jellyfin 10.11.11, 2026-09-01]`. A rename route that
    un-names a playlist is a request no client sends and no client can have built on, so it is
    refused here in the shape the route already refuses an incomplete body: the status is the
    whole of the difference, and the playlist keeps its name.
    """
    as_user(harness, harness.admin)
    playlist = world.public_playlist
    before = (await item(client, playlist.id))["Name"]

    body = rename_body(None)
    if how == "absent":
        del body["Name"]

    answered = await rename(client, playlist.id, body)
    assert answered.status_code == 400, answered.content
    assert answered.content == CONTROLLER_BODY
    assert answered.headers["content-type"] == "text/plain"
    assert (await item(client, playlist.id))["Name"] == before


@pytest.mark.parametrize("name", ["", "   "])
async def test_an_empty_or_blank_name_is_applied_as_sent(
    client: httpx.AsyncClient, harness: Harness, world: QueryWorld, name: str
) -> None:
    """Parity with the creation route's own finding: there is no validation on a playlist's name
    anywhere, and the reference stores an empty or blank one exactly as it arrives (AC-2)."""
    as_user(harness, harness.admin)
    playlist = world.public_playlist

    assert (await rename(client, playlist.id, rename_body(name))).status_code == 204
    assert (await item(client, playlist.id))["Name"] == name


async def test_the_properties_beside_name_are_ignored(
    client: httpx.AsyncClient, harness: Harness, world: QueryWorld
) -> None:
    """The recorded gap (behaviours section 5), asserted rather than described.

    The reference applies `Overview`, `ForcedSortName`, `OfficialRating`, `CustomRating`,
    `ProductionYear`, `Genres` and `Tags` from the same body it takes `Name` from - measured, on
    a body carrying all of them `[probe: tools/probe_playlist_rename.py, Jellyfin 10.11.11,
    2026-09-01]`. v1 applies `Name` and nothing else, so a client that edited a playlist's
    overview would find it unchanged. Named here so the narrowing cannot be mistaken for one
    nobody measured.
    """
    as_user(harness, harness.admin)
    playlist = world.public_playlist

    answered = await rename(
        client,
        playlist.id,
        rename_body(
            "Only The Name",
            Overview="an overview the route does not apply",
            OfficialRating="PG-13",
            ProductionYear=1997,
            Genres=["Not A Genre Of This Playlist"],
            Tags=["not-a-tag"],
        ),
    )
    assert answered.status_code == 204, answered.content

    renamed = await item(client, playlist.id)
    assert renamed["Name"] == "Only The Name"
    assert renamed.get("Overview") is None
    assert renamed.get("OfficialRating") is None
    assert renamed.get("ProductionYear") is None
    assert renamed.get("Genres", []) == []
    assert renamed.get("Tags", []) == []


@pytest.mark.parametrize("kind", ["a film", "an album", "a genre"])
async def test_anything_that_is_not_a_playlist_is_the_empty_403(
    client: httpx.AsyncClient, harness: Harness, world: QueryWorld, kind: str
) -> None:
    """The refusal this feature invents on this route, and it is the *empty* shape rather than
    the deletion's 25 bytes (009 plan section 6.6).

    The reference would apply the whole body to any item type. v1 has a consumer for none of that
    and could not honour it anyway - 004 T10 measured the scan and the refresh fighting over
    `Item.name`, so a renamed film would be un-renamed by the next scan, which is Principle VI's
    plausible-looking stub. The shape is the one the route's other refusal carries, so a caller
    cannot tell "you are not an administrator" from "that is not a playlist".
    """
    as_user(harness, harness.admin)
    item_id = {"a film": world.corpus[0], "an album": world.album, "a genre": None}[kind]
    if item_id is None:
        genres = await client.get("/Genres", params={"limit": "1"})
        item_id = genres.json()["Items"][0]["Id"]
    before = (await item(client, item_id))["Name"]

    answered = await rename(client, item_id, rename_body("Renamed Media"))
    assert answered.status_code == 403, answered.content
    assert answered.content == b""
    assert "content-type" not in answered.headers
    assert (await item(client, item_id))["Name"] == before


async def test_an_unknown_identifier_is_the_problem_details_404_on_the_rename(
    client: httpx.AsyncClient, harness: Harness, world: QueryWorld
) -> None:
    """Measured, and it beats the body: an unknown identifier with a body the route would refuse
    is still the `404` `[probe: tools/probe_playlist_rename.py, Jellyfin 10.11.11, 2026-09-01]`.
    """
    as_user(harness, harness.admin)
    answered = await rename(client, ABSENT_ID, {"Name": "Nothing To Rename"})
    assert answered.status_code == 404, answered.content
    body = json.loads(answered.content)
    body.pop("traceId")
    assert body == {
        "type": "https://tools.ietf.org/html/rfc9110#section-15.5.5",
        "title": "Not Found",
        "status": 404,
    }


async def test_a_malformed_identifier_is_the_binders_validation_400_on_the_rename(
    client: httpx.AsyncClient, harness: Harness, world: QueryWorld
) -> None:
    """`itemId` binds as an identifier on this method too - measured on the **POST** rather than
    inherited from the `DELETE` that shares the path, because three of the four 009 routes bind
    that segment differently and inheriting is how a route ships the wrong refusal (T11, T12)."""
    as_user(harness, harness.admin)
    answered = await rename(client, "not-an-identifier", rename_body("Renamed"))
    assert answered.status_code == 400, answered.content
    assert validation_body(answered) == problem(
        {"itemId": ["The value 'not-an-identifier' is not valid."]}
    )


async def test_an_all_zeros_identifier_is_the_bare_text_400_on_the_rename(
    client: httpx.AsyncClient, harness: Harness, world: QueryWorld
) -> None:
    """`Guid.Empty` again, and it is refused before the lookup as it is on every other route that
    resolves an identifier (T10, T12)."""
    as_user(harness, harness.admin)
    answered = await rename(client, EMPTY_GUID, rename_body("Renamed"))
    assert answered.status_code == 400, answered.content
    assert answered.content == CONTROLLER_BODY
    assert answered.headers["content-type"] == "text/plain"


@pytest.mark.parametrize("spelling", ["dashed", "braced", "upper case"])
async def test_every_spelling_of_the_identifier_addresses_the_playlist(
    client: httpx.AsyncClient, harness: Harness, world: QueryWorld, spelling: str
) -> None:
    """The segment is parsed, so all four spellings address the item - unlike the *entry* id one
    route away, which is compared as text and moves nothing when it is dashed (T11). Measured on
    this method `[probe: tools/probe_playlist_rename.py, Jellyfin 10.11.11, 2026-09-01]`."""
    as_user(harness, harness.admin)
    playlist = world.public_playlist
    addressed = {
        "dashed": dashed(playlist.id),
        "braced": "{" + dashed(playlist.id) + "}",
        "upper case": playlist.id.upper(),
    }[spelling]

    answered = await rename(client, addressed, rename_body(f"Renamed {spelling}"))
    assert answered.status_code == 204, answered.content
    assert (await item(client, playlist.id))["Name"] == f"Renamed {spelling}"


async def test_a_body_that_does_not_bind_names_the_references_action_parameter(
    client: httpx.AsyncClient, harness: Harness, world: QueryWorld
) -> None:
    """behaviours section 1.11's action-parameter row, on the second route in this project to
    have a **required** body (007 T8, 009 T8).

    Measured on the reference: a body that is not JSON is answered `400` with both keys - the
    binder's own `$`, and `request` carrying `The request field is required.` - which is the
    reference's name for this action's parameter and therefore this route's
    `[probe: tools/probe_playlist_rename.py, Jellyfin 10.11.11, 2026-09-01]`. The sentence the
    binder writes under `$` is .NET's own and is not reproduced; the key that names the parameter
    is, which is the half a client keys on.
    """
    as_user(harness, harness.admin)
    answered = await client.post(
        f"/Items/{world.public_playlist.id}",
        content=b"{not json",
        headers={"content-type": "application/json"},
    )
    assert answered.status_code == 400, answered.content
    body = validation_body(answered)
    assert body["errors"]["request"] == ["The request field is required."]


async def test_the_rename_route_declares_the_references_parameters_and_no_others(
    app: FastAPI,
) -> None:
    """`itemId` in the path and nothing in the query `[spec: UpdateItem]`, asserted against the
    generated document - and the path object holds both methods, since the deletion T12 added
    lives at the same address."""
    operations = app.openapi()["paths"]["/Items/{itemId}"]
    assert set(operations) == {"get", "delete", "post"}
    parameters = operations["post"]["parameters"]
    assert [one["name"] for one in parameters if one["in"] == "path"] == ["itemId"]
    assert [one["name"] for one in parameters if one["in"] == "query"] == []


async def test_ac20_a_renamed_playlist_keeps_its_entries(
    client: httpx.AsyncClient, harness: Harness, world: QueryWorld
) -> None:
    """The rename touches three columns of one row, and nothing else about the playlist: its
    entries, their order and their ids are what they were. Asserted because `rename` writes
    through the item table rather than through the playlist one, and a write that reached the
    wrong row would be invisible on the name alone."""
    as_user(harness, harness.admin)
    playlist = world.public_playlist
    before = (await client.get(f"/Playlists/{playlist.id}/Items")).json()

    assert (
        await rename(client, playlist.id, rename_body("Still Holds Its Entries"))
    ).status_code == 204

    after = (await client.get(f"/Playlists/{playlist.id}/Items")).json()
    assert [row["Id"] for row in after["Items"]] == [row["Id"] for row in before["Items"]]
    assert [row["PlaylistItemId"] for row in after["Items"]] == [
        row["PlaylistItemId"] for row in before["Items"]
    ]
    assert after["TotalRecordCount"] == before["TotalRecordCount"]
