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

from atrium.api.images import CACHE_CONTROL_BARE, CACHE_CONTROL_TAGGED, CONSTANT_HEADERS
from atrium.config.paths import DataPaths
from atrium.server import create_app
from tests.conformance.test_auth_mechanisms import mechanisms
from tests.conftest import data_dir
from tests.fixtures.images import BACKDROP_SIZES, ImageWorld, build_image_world

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
    counts = app.state.ignored_parameters.counts
    assert ("/Items/{itemId}/Images/{imageType}", "percentPlayed") in counts
