# SPDX-License-Identifier: GPL-3.0-or-later
"""The two image routes on the wire: the header contract, the index forms, and the conditional pair.

Everything here is a claim about what a client receives. The half that carries the most weight is
the **header-set sweep**: every response this suite produces is compared to an exact set, absences
included, because the framework's convenient file response would ship an `ETag` the reference does
not send — a validator delta on every image in a library, arriving through a class somebody
reached for to save six lines.

The `200` set was read off a live response and is reproduced verbatim
`[probe: manual requests via tools/_probe.py, Jellyfin 10.11.11, 2026-08-28]`:

    Content-Type, Content-Length, Last-Modified, Cache-Control, Vary: Accept,
    Content-Disposition: attachment, transferMode.dlna.org, realTimeInfo.dlna.org

and a `304` is that set minus `Content-Length`, measured — `Content-Type` and the DLNA pair
included.
"""

from __future__ import annotations

import io
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from PIL import Image

from atrium.api.images import (
    CACHE_CONTROL_BARE,
    CACHE_CONTROL_TAGGED,
    CONSTANT_HEADERS,
    ImageTypeToken,
)
from atrium.config.paths import DataPaths
from atrium.server import create_app
from tests.conformance.golden import assert_golden
from tests.conformance.test_auth_mechanisms import mechanisms
from tests.conftest import data_dir
from tests.fixtures.images import BACKDROP_SIZES, SMALL_SIZE, ImageWorld, build_image_world

pytestmark = pytest.mark.conformance

#: What 001's middleware stamps on everything, plus what the framework adds to any response. Not
#: part of this feature's contract, and excluded from the set comparison so that the comparison is
#: about *this* route.
AMBIENT = frozenset({"server", "x-response-time-ms"})

#: The `200` set, exactly. A header here and not on the wire fails; a header on the wire and not
#: here fails just as loudly, which is the half that catches `ETag`.
EXPECTED_200 = frozenset(
    {
        "content-type",
        "content-length",
        "last-modified",
        "cache-control",
        "vary",
        "content-disposition",
        "transfermode.dlna.org",
        "realtimeinfo.dlna.org",
    }
)

#: Measured: the `200`'s set minus `Content-Length`.
EXPECTED_304 = EXPECTED_200 - {"content-length"}

#: Named so a failure says which one arrived rather than "the sets differ".
NEVER = ("etag", "accept-ranges")


@pytest.fixture
def world_app(tmp_path: Path) -> Iterator[tuple[FastAPI, ImageWorld, DataPaths]]:
    paths: DataPaths = data_dir(tmp_path / "atrium")
    built = create_app(paths)
    built.state.readiness.mark_ready()
    with built.state.sessions.begin() as opened:
        world = build_image_world(opened, tmp_path / "libraries", paths.root)
    yield built, world, paths
    built.state.db.dispose()


@pytest.fixture
async def client(
    world_app: tuple[FastAPI, ImageWorld, DataPaths],
) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=world_app[0])
    async with httpx.AsyncClient(transport=transport, base_url="http://atrium:8096") as opened:
        yield opened


@pytest.fixture
def world(world_app: tuple[FastAPI, ImageWorld, DataPaths]) -> ImageWorld:
    return world_app[1]


def names(response: httpx.Response) -> frozenset[str]:
    return frozenset(name.lower() for name in response.headers) - AMBIENT


def decoded(payload: bytes) -> Image.Image:
    return Image.open(io.BytesIO(payload))


def recorded(app: FastAPI) -> dict[tuple[str, str], int]:
    """What the server was sent and did not act on, per `(route, parameter)` - the trail 005
    section 6.12 built and this feature inherits without a line of image code."""
    counts: dict[tuple[str, str], int] = app.state.ignored_parameters.counts
    return counts


# ------------------------------------------------------------------------------------------
# AC-3 and the header contract
# ------------------------------------------------------------------------------------------


async def test_ac3_the_bytes_come_back_with_a_real_type_and_an_exact_length(
    client: httpx.AsyncClient, world: ImageWorld
) -> None:
    answered = await client.get(f"/Items/{world.poster}/Images/Primary")

    assert answered.status_code == 200
    assert answered.content == world.drawn.poster
    assert answered.headers["content-type"] == "image/jpeg"
    assert answered.headers["content-length"] == str(len(world.drawn.poster))


async def test_the_header_set_on_a_bare_200_is_exactly_the_measured_one(
    client: httpx.AsyncClient, world: ImageWorld
) -> None:
    answered = await client.get(f"/Items/{world.poster}/Images/Primary")

    assert names(answered) == EXPECTED_200
    assert answered.headers["cache-control"] == CACHE_CONTROL_BARE
    for header, value in CONSTANT_HEADERS.items():
        assert answered.headers[header] == value


async def test_a_tagged_url_is_immutable_and_only_a_tagged_one(
    client: httpx.AsyncClient, world: ImageWorld
) -> None:
    """Both values measured verbatim. Only the `tag` makes the URL immutable, so only a tagged
    request gets a year of `max-age`."""
    tagged = await client.get(f"/Items/{world.poster}/Images/Primary", params={"tag": "whatever"})
    bare = await client.get(f"/Items/{world.poster}/Images/Primary")

    assert tagged.headers["cache-control"] == CACHE_CONTROL_TAGGED
    assert bare.headers["cache-control"] == CACHE_CONTROL_BARE
    assert names(tagged) == EXPECTED_200


@pytest.mark.parametrize("header", NEVER)
async def test_the_two_headers_that_must_not_exist_do_not(
    client: httpx.AsyncClient, world: ImageWorld, header: str
) -> None:
    """`ETag` is what `FileResponse` would add, and the reference sends none on an image;
    `Accept-Ranges` was in this spec's draft and the measured reference does not send it either.
    Asserted by name so a failure says which one came back."""
    for path in (
        f"/Items/{world.poster}/Images/Primary",
        f"/Items/{world.backdrops}/Images/Backdrop/1",
        f"/Items/{world.logo}/Images/Logo?maxWidth=100",
    ):
        answered = await client.get(path)
        assert header not in answered.headers, path


async def test_the_header_set_holds_across_the_whole_request_battery(
    client: httpx.AsyncClient, world: ImageWorld
) -> None:
    """The sweep of plan §8: every canonical request shape, one set."""
    battery = [
        f"/Items/{world.poster}/Images/Primary",
        f"/Items/{world.poster}/Images/Primary?maxWidth=300",
        f"/Items/{world.poster}/Images/Primary?fillWidth=300&fillHeight=300",
        f"/Items/{world.poster}/Images/Primary?width=200&height=200&quality=50",
        f"/Items/{world.poster}/Images/Primary?format=Png",
        f"/Items/{world.poster}/Images/Primary?tag=abc",
        f"/Items/{world.small}/Images/Primary?maxWidth=4000",
        f"/Items/{world.logo}/Images/Logo",
        f"/Items/{world.backdrops}/Images/Backdrop",
        f"/Items/{world.backdrops}/Images/Backdrop/2",
        f"/Items/{world.embedded}/Images/Primary",
        f"/Items/{world.remote}/Images/Primary",
    ]
    for path in battery:
        answered = await client.get(path)
        assert answered.status_code == 200, path
        assert names(answered) == EXPECTED_200, path


async def test_the_response_time_header_rides_along_like_everywhere_else(
    client: httpx.AsyncClient, world: ImageWorld
) -> None:
    """001's middleware is outermost, so it wraps these routes without their knowing."""
    answered = await client.get(f"/Items/{world.poster}/Images/Primary")

    assert "x-response-time-ms" in answered.headers
    assert answered.headers["server"].startswith("Atrium/")


# ------------------------------------------------------------------------------------------
# The indexed form, and the query spelling of it
# ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("index", range(len(BACKDROP_SIZES)))
async def test_the_indexed_form_selects_the_backdrop_it_names(
    client: httpx.AsyncClient, world: ImageWorld, index: int
) -> None:
    """Spec §6's "Indexed form" row, and it is assertible because the three backdrops are three
    different sizes: the reply is **decoded** and its size read, rather than the row trusted."""
    answered = await client.get(f"/Items/{world.backdrops}/Images/Backdrop/{index}")

    assert answered.status_code == 200
    assert decoded(answered.content).size == BACKDROP_SIZES[index]


@pytest.mark.parametrize("index", range(len(BACKDROP_SIZES)))
async def test_the_query_spelling_selects_the_same_backdrop(
    client: httpx.AsyncClient, world: ImageWorld, index: int
) -> None:
    """`?imageIndex=1` is in the pinned document on the unindexed route `[spec: GetItemImage]` and
    the reference honours it, measured. The two spellings answer the same bytes."""
    path = await client.get(f"/Items/{world.backdrops}/Images/Backdrop/{index}")
    query = await client.get(
        f"/Items/{world.backdrops}/Images/Backdrop", params={"imageIndex": str(index)}
    )

    assert query.status_code == 200
    assert query.content == path.content
    assert decoded(query.content).size == BACKDROP_SIZES[index]


async def test_the_unindexed_form_is_index_zero(
    client: httpx.AsyncClient, world: ImageWorld
) -> None:
    bare = await client.get(f"/Items/{world.backdrops}/Images/Backdrop")
    zero = await client.get(f"/Items/{world.backdrops}/Images/Backdrop/0")

    assert bare.content == zero.content


# ------------------------------------------------------------------------------------------
# AC-9 and AC-10: the conditional pair, and the tag that selects nothing
# ------------------------------------------------------------------------------------------


async def test_ac9_if_modified_since_at_the_sent_date_is_an_empty_304(
    client: httpx.AsyncClient, world: ImageWorld
) -> None:
    first = await client.get(f"/Items/{world.poster}/Images/Primary")

    conditional = await client.get(
        f"/Items/{world.poster}/Images/Primary",
        headers={"If-Modified-Since": first.headers["last-modified"]},
    )

    assert conditional.status_code == 304
    assert conditional.content == b""
    assert names(conditional) == EXPECTED_304
    assert conditional.headers["last-modified"] == first.headers["last-modified"]


async def test_the_304_carries_the_type_the_200_would_have(
    client: httpx.AsyncClient, world: ImageWorld
) -> None:
    """Measured on the reference, negotiation included: a conditional request offering
    `image/webp` on a resized image answers `304` with `Content-Type: image/webp`, and the same
    request without the offer answers `image/jpeg`."""
    offer = {"Accept": "image/webp,*/*"}
    resized = await client.get(f"/Items/{world.poster}/Images/Primary?maxWidth=300", headers=offer)
    assert resized.headers["content-type"] == "image/webp"

    conditional = await client.get(
        f"/Items/{world.poster}/Images/Primary?maxWidth=300",
        headers={**offer, "If-Modified-Since": resized.headers["last-modified"]},
    )

    assert conditional.status_code == 304
    assert conditional.headers["content-type"] == "image/webp"


async def test_an_older_if_modified_since_is_answered_with_the_image(
    client: httpx.AsyncClient, world: ImageWorld
) -> None:
    answered = await client.get(
        f"/Items/{world.poster}/Images/Primary",
        headers={"If-Modified-Since": "Wed, 01 Jan 2020 00:00:00 GMT"},
    )

    assert answered.status_code == 200
    assert answered.content == world.drawn.poster


async def test_an_unparseable_if_modified_since_is_ignored_rather_than_refused(
    client: httpx.AsyncClient, world: ImageWorld
) -> None:
    """Measured: `If-Modified-Since: banana` answers `200`."""
    answered = await client.get(
        f"/Items/{world.poster}/Images/Primary", headers={"If-Modified-Since": "banana"}
    )

    assert answered.status_code == 200


async def test_ac10_a_stale_tag_answers_200_with_the_current_image(
    client: httpx.AsyncClient, world: ImageWorld
) -> None:
    """The `tag` never reaches selection. A client asking by a tag the item no longer has is
    behind, not wrong, and failing here empties a user's grid during a refresh."""
    stale = await client.get(f"/Items/{world.poster}/Images/Primary", params={"tag": "0" * 32})
    untagged = await client.get(f"/Items/{world.poster}/Images/Primary")

    assert stale.status_code == 200
    assert stale.content == untagged.content == world.drawn.poster


# ------------------------------------------------------------------------------------------
# AC-12: no token, every token
# ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("mechanism", [name for name, _, _ in mechanisms("x")])
@pytest.mark.parametrize(
    "token", ["0" * 32, "not-a-token", ""], ids=["unknown", "malformed", "empty"]
)
async def test_ac12_every_mechanism_is_accepted_and_none_changes_the_answer(
    client: httpx.AsyncClient, world: ImageWorld, mechanism: str, token: str
) -> None:
    """Parameterised over 002 §3.1's own enumeration — **imported, not copied**, so a sixth
    mechanism discovered later reaches this route's test by existing.

    The route reads no token at all, so an unknown and a malformed one are accepted the only way
    "accepted" is visible: the answer does not change. Measured on the reference, which answers
    the identical `200` to all of them.
    """
    tokenless = await client.get(f"/Items/{world.poster}/Images/Primary")
    headers, query = next((h, q) for name, h, q in mechanisms(token) if name == mechanism)

    answered = await client.get(
        f"/Items/{world.poster}/Images/Primary", headers=headers, params=query
    )

    assert tokenless.status_code == 200
    assert answered.status_code == 200
    assert answered.content == tokenless.content == world.drawn.poster


# ------------------------------------------------------------------------------------------
# The parameter plumbing 005 §6.12 supplies for free
# ------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "spelling",
    ["maxWidth", "MAXWIDTH", "maxwidth", "MaxWidth"],
)
async def test_every_declared_parameter_survives_a_mangled_spelling(
    client: httpx.AsyncClient, world: ImageWorld, spelling: str
) -> None:
    """005 §8's per-route battery, on an image route: parameter names match case-insensitively
    (behaviours §1.15) and the canonicalising middleware is what makes that true for a route that
    does nothing to earn it."""
    answered = await client.get(f"/Items/{world.poster}/Images/Primary?{spelling}=300")

    assert answered.status_code == 200
    assert decoded(answered.content).size == (300, 450), spelling


@pytest.mark.parametrize(
    "parameter,value,expected",
    [
        ("fillWidth", "300", (300, 450)),
        ("fillHeight", "450", (300, 450)),
        ("width", "300", (300, 450)),
        ("height", "450", (300, 450)),
        ("maxHeight", "450", (300, 450)),
        ("format", "Png", None),
        ("quality", "40", None),
        ("tag", "abc", None),
    ],
)
async def test_every_declared_parameter_reaches_the_route_upper_cased(
    client: httpx.AsyncClient,
    world: ImageWorld,
    parameter: str,
    value: str,
    expected: tuple[int, int] | None,
) -> None:
    """Each declared spelling, sent in a casing no client uses, still binds. A parameter that
    silently stopped binding would look like a client that never scrolls (005's own lesson)."""
    mangled = parameter.upper()
    answered = await client.get(f"/Items/{world.poster}/Images/Primary?{mangled}={value}")

    assert answered.status_code == 200, f"{mangled}={value}"
    if expected is not None:
        assert decoded(answered.content).size == expected


async def test_an_undeclared_decoration_parameter_is_recorded_and_ignored(
    client: httpx.AsyncClient, world_app: tuple[FastAPI, ImageWorld, DataPaths]
) -> None:
    """OQ-4's measurable trail, and it exists without a line of image code: the five decoration
    parameters are undeclared on purpose, and an undeclared parameter is what the recorder counts
    per `(route, parameter)`."""
    app, world, _paths = world_app

    answered = await client.get(
        f"/Items/{world.poster}/Images/Primary", params={"percentPlayed": "40"}
    )

    assert answered.status_code == 200
    assert answered.content == world.drawn.poster, "undecorated, which is the declared v1 gap"
    assert ("/Items/{itemId}/Images/{imageType}", "percentPlayed") in recorded(app)


# ------------------------------------------------------------------------------------------
# AC-11: the error matrix, and the split held by bytes
# ------------------------------------------------------------------------------------------

#: The `traceId` is per request by definition (behaviours §1.11), so it is the one value a golden
#: here has to substitute. Everything else in these bodies is fixed.
TRACE_PLACEHOLDER = "00-<trace>-<span>-00"


def traced(response: httpx.Response) -> dict[str, str]:
    """The placeholder map for a problem-details golden: the one unstable value, by its value."""
    return {response.json()["traceId"]: TRACE_PLACEHOLDER}


async def test_ac11_an_unknown_item_is_the_problem_details_404(
    client: httpx.AsyncClient, world: ImageWorld, pytestconfig: pytest.Config
) -> None:
    """The first of the route's **two** `404` bodies. Measured byte for byte against a live
    reference at T3, and the split is what behaviours §1.11's fourth shape exists to record."""
    answered = await client.get(f"/Items/{'f' * 32}/Images/Primary")

    assert answered.status_code == 404
    assert_golden(
        "Images.Error.UnknownItem", answered, config=pytestconfig, placeholders=traced(answered)
    )


async def test_a_removed_item_answers_the_same_bytes_as_an_unknown_one(
    client: httpx.AsyncClient, world: ImageWorld
) -> None:
    """The world a client browses has no removed items in it, and this route must not disagree
    with the lists — the same rule 005 AC-8 states for `/Items/{itemId}`."""
    unknown = await client.get(f"/Items/{'f' * 32}/Images/Primary")
    removed = await client.get(f"/Items/{world.removed}/Images/Primary")

    assert removed.status_code == unknown.status_code == 404
    assert removed.json()["title"] == unknown.json()["title"]
    assert removed.json()["status"] == unknown.json()["status"] == 404


async def test_ac11_an_item_that_lacks_the_type_is_the_message_shape(
    client: httpx.AsyncClient, world: ImageWorld, pytestconfig: pytest.Config
) -> None:
    """The other `404`: a JSON-encoded bare string naming the item and the type. Same status as
    the one above and not one byte in common, which no test asserting a status could tell."""
    answered = await client.get(f"/Items/{world.imageless}/Images/Primary")

    assert answered.status_code == 404
    assert answered.headers["content-type"] == "application/json; charset=utf-8"
    assert_golden("Images.Error.AbsentType", answered, config=pytestconfig)


async def test_ac11_an_index_past_the_last_backdrop_names_the_type_not_the_index(
    client: httpx.AsyncClient, world: ImageWorld
) -> None:
    """Measured: `Backdrop/99` answers "…does not have an image of type **Backdrop**". A message
    built from the index would read plausibly and differ from the reference on every request."""
    answered = await client.get(f"/Items/{world.backdrops}/Images/Backdrop/{len(BACKDROP_SIZES)}")

    assert answered.status_code == 404
    assert answered.json() == "The Backdrops does not have an image of type Backdrop"


@pytest.mark.parametrize("member", ["Box", "BoxRear", "Menu", "Screenshot", "Profile"])
async def test_a_vocabulary_member_v1_never_stores_is_the_message_404(
    client: httpx.AsyncClient, world: ImageWorld, member: str
) -> None:
    """The five members no v1 writer creates. They are `404`s and **not** `400`s, which is what
    proves the vocabulary parse admits all thirteen: `Box` measured `404` on the reference while a
    string outside the enum measured `400`
    `[probe: tools/probe_image_formats.py, Jellyfin 10.11.11, 2026-08-28]`.
    """
    answered = await client.get(f"/Items/{world.poster}/Images/{member}")

    assert answered.status_code == 404
    assert answered.json() == f"The Poster does not have an image of type {member}"


async def test_ac11_a_type_outside_the_vocabulary_is_the_validation_400(
    client: httpx.AsyncClient, world: ImageWorld, pytestconfig: pytest.Config
) -> None:
    """Keyed on the **declared** spelling, `imageType`, and worded as the reference words it."""
    answered = await client.get(f"/Items/{world.poster}/Images/NotAnImageType")

    assert answered.status_code == 400
    assert_golden(
        "Images.Error.UnknownImageType",
        answered,
        config=pytestconfig,
        placeholders=traced(answered),
    )


@pytest.mark.parametrize("parameter", ["maxWidth", "maxHeight", "width", "height", "quality"])
async def test_an_unparseable_dimension_or_quality_is_the_validation_400(
    client: httpx.AsyncClient, world: ImageWorld, parameter: str
) -> None:
    """The one measured error path on this route that is **not** lenient (spec §3.2), and the
    `errors` key is the declared spelling rather than the client's."""
    answered = await client.get(f"/Items/{world.poster}/Images/Primary?{parameter}=banana")

    assert answered.status_code == 400
    assert answered.json()["errors"] == {parameter: ["The value 'banana' is not valid."]}


async def test_the_dimension_400_is_the_measured_body(
    client: httpx.AsyncClient, world: ImageWorld, pytestconfig: pytest.Config
) -> None:
    answered = await client.get(f"/Items/{world.poster}/Images/Primary?maxWidth=banana")

    assert_golden(
        "Images.Error.UnparseableDimension",
        answered,
        config=pytestconfig,
        placeholders=traced(answered),
    )


async def test_a_malformed_item_id_is_the_validation_400_keyed_on_item_id(
    client: httpx.AsyncClient, world: ImageWorld
) -> None:
    answered = await client.get("/Items/not-a-guid/Images/Primary")

    assert answered.status_code == 400
    assert answered.json()["errors"] == {"itemId": ["The value 'not-a-guid' is not valid."]}


# ------------------------------------------------------------------------------------------
# The lenient half: values that parse and are forgiven
# ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["-100", "0"])
async def test_a_non_positive_dimension_is_forgiven_with_the_image(
    client: httpx.AsyncClient, world: ImageWorld, value: str
) -> None:
    """`maxWidth=-100` answers `200`, measured. A `ge=0` bound on the parameter would manufacture
    a `400` the reference does not send — which is why the routes declare no range at all."""
    answered = await client.get(f"/Items/{world.poster}/Images/Primary?maxWidth={value}")

    assert answered.status_code == 200
    assert answered.content == world.drawn.poster


async def test_an_unknown_format_token_is_dropped_recorded_and_answered(
    client: httpx.AsyncClient, world_app: tuple[FastAPI, ImageWorld, DataPaths]
) -> None:
    """behaviours §1.12's shape, on the one parameter of this route that has it. `format=Banana`
    answers `200` with the value ignored — measured — and the drop is counted, which is what makes
    the leniency a decision with a trail rather than a silence."""
    app, world, _paths = world_app

    answered = await client.get(f"/Items/{world.poster}/Images/Primary?format=Banana")

    assert answered.status_code == 200
    assert answered.content == world.drawn.poster
    assert ("/Items/{itemId}/Images/{imageType}", "format=Banana") in recorded(app)


async def test_a_vocabulary_format_this_build_cannot_encode_falls_back_and_is_recorded(
    client: httpx.AsyncClient, world_app: tuple[FastAPI, ImageWorld, DataPaths]
) -> None:
    """`Bmp` and `Gif` parse — they are members — and fall back to the source format **with the
    transform still applied**: `format=Bmp` at `maxWidth=200` measured a 200px JPEG out of a JPEG
    source. Two different drops, one recorder."""
    app, world, _paths = world_app

    answered = await client.get(f"/Items/{world.poster}/Images/Primary?format=Bmp&maxWidth=300")

    assert answered.status_code == 200
    assert answered.headers["content-type"] == "image/jpeg"
    assert decoded(answered.content).size == (300, 450)
    assert ("/Items/{itemId}/Images/{imageType}", "format=Bmp") in recorded(app)


# ------------------------------------------------------------------------------------------
# Chapter, and the tripwire that says when this feature has to grow
# ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["Chapter", "Chapter/0", "Chapter/7"])
async def test_a_chapter_image_answers_the_message_404_today(
    client: httpx.AsyncClient, world: ImageWorld, path: str
) -> None:
    """v1 serves chapter images that exist and never generates them (spec §3.5), and nothing in
    v1 creates a chapter row — so every chapter request is the absent-image `404`. That is the
    same wire a client sees from a reference that has not finished generating them."""
    answered = await client.get(f"/Items/{world.poster}/Images/{path}")

    assert answered.status_code == 404
    assert answered.json() == "The Poster does not have an image of type Chapter"


def test_no_v1_writer_can_create_a_chapter_row() -> None:
    """**The tripwire.** The day something starts writing `Chapter` rows, this fails — and that
    failure is the signal to extend this feature rather than a bug to work around.

    Structural rather than empirical: `MetadataRepository.apply` writes an `ImageAssociation`, an
    `ImageAssociation` carries an `ImageKind`, and `ImageKind` is the seven types a *local file*
    can be. A test that scanned a library and found no chapter rows would pass for as long as
    nobody put one in the fixture; this cannot pass once the vocabulary the write path accepts
    grows a member.
    """
    from atrium.metadata.artwork import ImageAssociation, ImageKind

    writable = {kind.value for kind in ImageKind}
    never_written = {member.value for member in ImageTypeToken} - writable

    assert "Chapter" in never_written
    assert never_written == {"Chapter", "Box", "BoxRear", "Menu", "Screenshot", "Profile"}
    assert ImageAssociation.__annotations__["kind"] == "ImageKind"


def test_the_never_stored_members_are_the_ones_the_error_matrix_names() -> None:
    """The five of plan §6.1 plus `Chapter`, which has its own story (spec §3.5). Written as one
    assertion so a member moving between the two lists cannot happen silently."""
    from atrium.metadata.artwork import ImageKind

    assert {member.value for member in ImageTypeToken} - {kind.value for kind in ImageKind} == {
        "Box",
        "BoxRear",
        "Menu",
        "Profile",
        "Screenshot",
        "Chapter",
    }


# ------------------------------------------------------------------------------------------
# The resize and format matrix, through the whole stack
# ------------------------------------------------------------------------------------------

#: `(label, query, the size the reply decodes to)`. The unit half of this table is
#: `tests/unit/test_image_transform.py`; what these rows add is that the plumbing delivers what
#: the pure module decided — a route that dropped a parameter on the floor would pass every test
#: there and fail every one here.
#:
#: The source is the 1000x1500 poster, whose 2:3 ratio is what tells a cover from a fit and an
#: exact box from an aspect-true one.
WIRE_GEOMETRY = [
    ("AC-4: maxWidth=300", {"maxWidth": "300"}, (300, 450)),
    ("maxHeight=300", {"maxHeight": "300"}, (200, 300)),
    ("AC-6: fill 300x300 covers", {"fillWidth": "300", "fillHeight": "300"}, (300, 450)),
    (
        "AC-6: fill 500x1500, off the ratio",
        {"fillWidth": "500", "fillHeight": "1500"},
        (1000, 1500),
    ),
    ("the distorted exact box", {"width": "300", "height": "300"}, (300, 300)),
    ("a lone width keeps the ratio", {"width": "300"}, (300, 450)),
    ("the exact path upscales", {"width": "2000", "height": "3000"}, (2000, 3000)),
    ("maxWidth caps the exact size afterwards", {"width": "2000", "maxWidth": "500"}, (500, 750)),
    (
        "fill composed with maxWidth",
        {"fillWidth": "500", "fillHeight": "300", "maxWidth": "200"},
        (200, 300),
    ),
]


@pytest.mark.parametrize(
    "label,query,delivered", WIRE_GEOMETRY, ids=[row[0] for row in WIRE_GEOMETRY]
)
async def test_the_resize_matrix_delivers_what_it_decided(
    client: httpx.AsyncClient,
    world: ImageWorld,
    label: str,
    query: dict[str, str],
    delivered: tuple[int, int],
) -> None:
    answered = await client.get(f"/Items/{world.poster}/Images/Primary", params=query)

    assert answered.status_code == 200, label
    assert decoded(answered.content).size == delivered, label


async def test_ac5_a_box_past_the_source_is_the_source_file_byte_for_byte(
    client: httpx.AsyncClient, world: ImageWorld
) -> None:
    """`maxWidth=2000` of the 400px source. Byte-identical rather than merely the right size,
    which is what the verbatim path buys and what makes AC-8 and AC-13 true by construction."""
    answered = await client.get(f"/Items/{world.small}/Images/Primary", params={"maxWidth": "2000"})

    assert answered.content == world.drawn.small
    assert decoded(answered.content).size == SMALL_SIZE


async def test_ac6_a_fill_box_the_source_cannot_cover_returns_it_unchanged(
    client: httpx.AsyncClient, world: ImageWorld
) -> None:
    answered = await client.get(
        f"/Items/{world.poster}/Images/Primary",
        params={"fillWidth": "4000", "fillHeight": "6000"},
    )

    assert answered.content == world.drawn.poster


async def test_ac7_a_resized_logo_keeps_its_alpha(
    client: httpx.AsyncClient, world: ImageWorld
) -> None:
    """A logo silently served as JPEG acquires a white box, immediately visible on any dark
    client theme. Transparency is never discarded implicitly (spec §3.3)."""
    answered = await client.get(f"/Items/{world.logo}/Images/Logo", params={"maxWidth": "300"})
    result = decoded(answered.content)

    assert answered.headers["content-type"] == "image/png"
    assert result.mode == "RGBA"
    assert result.getchannel("A").getextrema()[0] == 0


async def test_ac7_an_explicit_jpg_takes_the_alpha_and_that_is_measured(
    client: httpx.AsyncClient, world: ImageWorld
) -> None:
    """The transparent logo comes back opaque under `format=Jpg` on the reference, so refusing
    what the client asked for by name would be the real divergence."""
    answered = await client.get(
        f"/Items/{world.logo}/Images/Logo", params={"maxWidth": "300", "format": "Jpg"}
    )

    assert answered.headers["content-type"] == "image/jpeg"
    assert decoded(answered.content).mode == "RGB"


@pytest.mark.parametrize(
    "asked,expected",
    [("Png", "image/png"), ("Jpg", "image/jpeg"), ("Webp", "image/webp")],
)
async def test_each_encodable_format_is_honoured_by_name(
    client: httpx.AsyncClient, world: ImageWorld, asked: str, expected: str
) -> None:
    answered = await client.get(
        f"/Items/{world.poster}/Images/Primary", params={"maxWidth": "300", "format": asked}
    )

    assert answered.headers["content-type"] == expected
    assert decoded(answered.content).size == (300, 450)


async def test_svg_short_circuits_to_the_source_with_the_resize_ignored(
    client: httpx.AsyncClient, world: ImageWorld
) -> None:
    """Measured: an 800px source came back **whole** against `maxWidth=200`. `Svg` is not a
    fallback like `Bmp` and `Gif` — the resize is ignored rather than applied."""
    answered = await client.get(
        f"/Items/{world.poster}/Images/Primary", params={"format": "Svg", "maxWidth": "200"}
    )

    assert answered.content == world.drawn.poster
    assert answered.headers["content-type"] == "image/jpeg"


# ------------------------------------------------------------------------------------------
# AC-15: the three negotiation cells
# ------------------------------------------------------------------------------------------

WEBP_OFFER = "image/webp,image/*;q=0.8,*/*;q=0.5"


async def test_ac15_a_resized_response_negotiates_webp_under_vary_accept(
    client: httpx.AsyncClient, world: ImageWorld
) -> None:
    """The finding the plan's own §10 had argued against, until one request reversed it: every
    browser-based client makes this offer on every poster it loads."""
    answered = await client.get(
        f"/Items/{world.poster}/Images/Primary",
        params={"maxWidth": "300"},
        headers={"Accept": WEBP_OFFER},
    )

    assert answered.headers["content-type"] == "image/webp"
    assert answered.headers["vary"] == "Accept"
    assert decoded(answered.content).size == (300, 450)


async def test_ac15_an_explicit_format_beats_the_offer(
    client: httpx.AsyncClient, world: ImageWorld
) -> None:
    answered = await client.get(
        f"/Items/{world.poster}/Images/Primary",
        params={"maxWidth": "300", "format": "Png"},
        headers={"Accept": WEBP_OFFER},
    )

    assert answered.headers["content-type"] == "image/png"


async def test_ac15_a_verbatim_request_negotiates_nothing(
    client: httpx.AsyncClient, world: ImageWorld
) -> None:
    """The cell the earlier probe was blind to, from the other side: it made the offer only on a
    request nothing transformed and read the source format back as "no negotiation"."""
    answered = await client.get(
        f"/Items/{world.poster}/Images/Primary", headers={"Accept": WEBP_OFFER}
    )

    assert answered.headers["content-type"] == "image/jpeg"
    assert answered.content == world.drawn.poster
    assert answered.headers["vary"] == "Accept", "sent either way, which is what Vary means"


async def test_an_avif_offer_is_not_negotiated(
    client: httpx.AsyncClient, world: ImageWorld
) -> None:
    """Measured. A server that negotiated AVIF because it could would be a delta on every client
    that offers one."""
    answered = await client.get(
        f"/Items/{world.poster}/Images/Primary",
        params={"maxWidth": "300"},
        headers={"Accept": "image/avif,image/*;q=0.8,*/*;q=0.5"},
    )

    assert answered.headers["content-type"] == "image/jpeg"
