# SPDX-License-Identifier: GPL-3.0-or-later
"""The fourth error shape, pinned to the bytes it was measured as.

One route, two `404` bodies. `GET /Items/{itemId}/Images/{imageType}` refuses an item that does
not exist with problem details and an item that exists but has no such image with a **JSON-encoded
bare string** — the split is which of the two lookups failed, and behaviours §1.11 records it
because nothing about a status code says which one a client received.

These run against a throwaway application, before `api/images.py` exists, for the reason the
module under test exists at all: the shape belongs to `compat/errors.py`, not to the route that
happens to raise it first, and a test that could only run through `/Items/{itemId}/Images` would
be testing that route.

**Bytes, not `.json()`.** The quoting is the shape: a parsed body cannot tell `"a message"` from
`{"detail": "a message"}` reading the same after `["detail"]`, and the whole point of §1.11 is
that the same status carries different bytes.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import APIRouter, FastAPI

from atrium.compat.errors import (
    EXCEPTION_HANDLERS,
    IMAGE_ABSENT_TEMPLATE,
    NOT_FOUND_TITLE,
    PROBLEM_TYPE_NOT_FOUND,
    ImageNotFoundError,
    ItemNotFoundError,
    image_absent_message,
)
from atrium.compat.responses import AtriumJSONResponse

#: The item this fixture refuses about, and the type it lacks. Both are the measured request's:
#: `GET /Items/{id}/Images/Box` on an item called `#1 to Infinity` answered
#: `"#1 to Infinity does not have an image of type Box"` in 51 bytes.
#: `[probe: manual requests via tools/_probe.py, Jellyfin 10.11.11, 2026-08-28]`
ITEM_NAME = "#1 to Infinity"
ABSENT_TYPE = "Box"

#: An item whose name is not ASCII, measured on the same server: `DW Español` came back as
#: `DW Espa\u00F1ol`, with **uppercase** hex (behaviours §1.16). Nothing about this route makes it
#: special — it is the response class's rule applied to a body that happens to be a bare string —
#: and it is asserted here so no later route re-fights it.
ODD_NAME = "DW Español"


def build_router() -> APIRouter:
    """Two routes, one per refusal. Neither does anything else."""
    router = APIRouter()

    @router.get("/Refuse/UnknownItem")
    async def unknown_item() -> None:  # pyright: ignore[reportUnusedFunction]
        raise ItemNotFoundError

    @router.get("/Refuse/AbsentImage")
    async def absent_image() -> None:  # pyright: ignore[reportUnusedFunction]
        raise ImageNotFoundError(ITEM_NAME, ABSENT_TYPE)

    @router.get("/Refuse/AbsentImageOnAnOddName")
    async def odd_name() -> None:  # pyright: ignore[reportUnusedFunction]
        raise ImageNotFoundError(ODD_NAME, ABSENT_TYPE)

    return router


@pytest.fixture
def app() -> FastAPI:
    built = FastAPI(
        default_response_class=AtriumJSONResponse, exception_handlers=dict(EXCEPTION_HANDLERS)
    )
    built.include_router(build_router())
    return built


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://atrium:8096") as opened:
        yield opened


# ------------------------------------------------------------------------------------------
# The two shapes, and the split between them
# ------------------------------------------------------------------------------------------


async def test_an_absent_image_is_the_message_as_a_quoted_json_string(
    client: httpx.AsyncClient,
) -> None:
    """The measured body, byte for byte, quotes included."""
    answered = await client.get("/Refuse/AbsentImage")

    assert answered.status_code == 404
    assert answered.content == b'"#1 to Infinity does not have an image of type Box"'
    assert len(answered.content) == 51


async def test_the_absent_image_body_carries_the_json_content_type_with_its_charset(
    client: httpx.AsyncClient,
) -> None:
    """`application/json; charset=utf-8` — measured, and **not** `text/plain`.

    The third shape is the one that sends text without a charset (behaviours §1.11); this one is
    JSON, and a handler that reached for `PlainTextResponse` because the body reads like a
    sentence would send neither the quotes nor this header.
    """
    answered = await client.get("/Refuse/AbsentImage")

    assert answered.headers["content-type"] == "application/json; charset=utf-8"


async def test_an_unknown_item_is_problem_details_on_the_same_route_class(
    client: httpx.AsyncClient,
) -> None:
    """The other `404`. Same status, and not one byte in common with the one above."""
    answered = await client.get("/Refuse/UnknownItem")
    body = answered.json()

    assert answered.status_code == 404
    assert body == {
        "type": PROBLEM_TYPE_NOT_FOUND,
        "title": NOT_FOUND_TITLE,
        "status": 404,
        "traceId": body["traceId"],
    }


async def test_the_two_refusals_share_a_status_and_nothing_else(
    client: httpx.AsyncClient,
) -> None:
    """The split, asserted as a difference rather than as two independent facts.

    This is the assertion that fails if somebody later maps both exceptions to one handler
    because "they are both 404s" — which is exactly what the measured wire says they are not.
    """
    absent = await client.get("/Refuse/AbsentImage")
    unknown = await client.get("/Refuse/UnknownItem")

    assert absent.status_code == unknown.status_code == 404
    assert absent.content != unknown.content
    assert not absent.content.startswith(b"{")
    assert unknown.content.startswith(b"{")


async def test_a_non_ascii_item_name_is_escaped_the_reference_s_way(
    client: httpx.AsyncClient,
) -> None:
    r"""`DW Español` goes out as `DW Espa\u00F1ol`, uppercase hex — behaviours §1.16.

    Measured on this exact refusal, which matters because §1.11's fourth shape is the only place
    an *item's own name* reaches a response body verbatim. §4.4 records an older decision to send
    the character itself; 005's response class reversed it, the reference agrees with the
    reversal, and this test is here so the next route to carry a name does not re-litigate it.
    `[probe: manual requests via tools/_probe.py, Jellyfin 10.11.11, 2026-08-28]`
    """
    answered = await client.get("/Refuse/AbsentImageOnAnOddName")

    assert answered.content == b'"DW Espa\\u00F1ol does not have an image of type Box"'
    assert "ñ".encode() not in answered.content
    assert answered.json() == image_absent_message(ODD_NAME, ABSENT_TYPE)


# ------------------------------------------------------------------------------------------
# The exception itself
# ------------------------------------------------------------------------------------------


def test_the_message_is_built_from_the_two_values_the_wire_shows() -> None:
    """The template is the reference's sentence, and both halves are interpolated."""
    assert image_absent_message("Amélie", "Logo") == "Amélie does not have an image of type Logo"
    assert IMAGE_ABSENT_TEMPLATE.count("{") == 2


def test_the_exception_keeps_what_it_was_raised_with() -> None:
    """Not only the rendered sentence: a route that wants to log the pair should not re-parse it."""
    raised = ImageNotFoundError("A Film", "Chapter")

    assert raised.item_name == "A Film"
    assert raised.image_type == "Chapter"
    assert str(raised) == "A Film does not have an image of type Chapter"


def test_the_item_refusal_is_a_not_found_error_so_one_handler_serves_both() -> None:
    """Starlette resolves a handler by walking the MRO, which is why `ItemNotFoundError` needs no
    row of its own — and why the name exists at all: plan §7 asks for the split to be verified by
    **type**, and two names is what makes that possible while one shape reaches the wire."""
    from atrium.compat.errors import NotFoundError

    assert issubclass(ItemNotFoundError, NotFoundError)
    assert not issubclass(ImageNotFoundError, NotFoundError)
    assert ItemNotFoundError not in EXCEPTION_HANDLERS
    assert EXCEPTION_HANDLERS[ImageNotFoundError] is not EXCEPTION_HANDLERS[NotFoundError]
