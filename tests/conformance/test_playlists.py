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
