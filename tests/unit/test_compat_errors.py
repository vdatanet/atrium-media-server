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
from enum import Enum
from typing import Any, ClassVar

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
    validation_errors,
)
from atrium.compat.model import AtriumModel, wire_ordinals
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


@wire_ordinals({0: "http", 1: "hls"})
class Protocol(Enum):
    """A vocabulary shaped like the reference's `MediaStreamProtocol`, ordinals and all.

    It exists so the **measured** nested refusal can be reproduced here before 012 T9 types the
    real property as an enumeration: the key the reference sends is
    `$.DeviceProfile.TranscodingProfiles[0].Protocol`, and until that field is a vocabulary the
    route cannot produce it `[probe: tools/probe_playback_info.py, Jellyfin 10.11.11,
    2026-09-03]`.
    """

    HTTP = "http"
    HLS = "hls"


class _Target(AtriumModel):
    """One transcoding entry, with the one property this file is about."""

    #: The reference's own name for the enumeration, as its refusal spells it in full. Measured
    #: on this very property `[probe: tools/probe_playback_info.py, Jellyfin 10.11.11,
    #: 2026-09-03]`.
    WIRE_ENUM_TYPES: ClassVar[dict[str, str]] = {
        "Protocol": "Jellyfin.Data.Enums.MediaStreamProtocol"
    }

    container: str = ""
    protocol: Protocol = Protocol.HTTP


class _Profile(AtriumModel):
    """The one list the path has to descend through, so a level is a list index."""

    transcoding_profiles: list[_Target] = []  # noqa: RUF012 - pydantic copies a default per model


class _Negotiation(AtriumModel):
    """The body, shaped like the negotiation's: a nested object, a list, an entry, a property.

    The field names are the reference's own because every `AtriumModel` anywhere is walked by the
    alias sweep - the convention `tests/unit/test_compat_model.py` states and this file follows.
    """

    user_id: str | None = None
    device_profile: _Profile | None = None


#: The measured key, byte for byte, and the sentence beside it. One `errors` entry, the path
#: repeated in `Path:`, and a `BytePositionInLine` that is an offset into the body as sent
#: `[probe: tools/probe_playback_info.py, Jellyfin 10.11.11, 2026-09-03]`.
NESTED_KEY = "$.DeviceProfile.TranscodingProfiles[0].Protocol"
NESTED_MESSAGE = (
    "The JSON value could not be converted to Jellyfin.Data.Enums.MediaStreamProtocol. "
    "Path: $.DeviceProfile.TranscodingProfiles[0].Protocol | LineNumber: {line} | "
    "BytePositionInLine: {position}."
)


def build_router() -> APIRouter:
    """Three routes, one per refusal. None of them does anything else."""
    router = APIRouter()

    @router.post("/Refuse/Negotiation")
    async def negotiation(  # pyright: ignore[reportUnusedFunction]
        playbackInfoDto: _Negotiation | None = None,  # noqa: N803 - the reference's spelling
    ) -> dict[str, bool]:
        return {"Bound": True}

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


# ------------------------------------------------------------------------------------------
# A failure inside a nested object is keyed by its JSON path (012 T8)
# ------------------------------------------------------------------------------------------
#
# The reference reports one vocabulary failure two ways, and the route decides which. On
# `POST /Playlists` a top-level property is keyed `$`, says `Path: $` and counts `len(token) + 2`
# wherever it sits; on the negotiation a property inside a device profile is keyed by its full
# JSON path, repeats that path, and counts a byte offset into the document as sent
# `[probe: tools/probe_playback_info.py, Jellyfin 10.11.11, 2026-09-03]`,
# `[probe: tools/probe_playlist_creation.py, Jellyfin 10.11.11, 2026-08-31]`. What is asserted
# here is the second shape on a body shaped like the negotiation's; the first is asserted where it
# was measured, in `tests/conformance/test_playlists.py`.

#: One line, which is what every measured body was — so `LineNumber` is `0` and the position is
#: the offset from the first byte.
ONE_LINE = (
    b'{"UserId":"a","DeviceProfile":{"TranscodingProfiles":[{"Container":"ts","Protocol":"dash"}]}}'
)

#: The same document a client's pretty-printer would send it as.
MANY_LINES = b"""{
  "DeviceProfile": {
    "TranscodingProfiles": [
      {"Container": "ts", "Protocol": "dash"}
    ]
  }
}"""


async def _refusal(client: httpx.AsyncClient, raw: bytes) -> dict[str, Any]:
    """One refusal of a body written byte for byte, because a byte offset is what is asserted."""
    answered = await client.post(
        "/Refuse/Negotiation", content=raw, headers={"Content-Type": "application/json"}
    )
    assert answered.status_code == 400, answered.content
    return dict(answered.json())["errors"]


def _token_ends_at(raw: bytes, token: bytes) -> int:
    """Where the offending token ends, found by searching the bytes rather than by walking them.

    Deliberately a different derivation from the one under test: an expectation computed by the
    same reader would be Atrium compared with itself, which is 001 T16's finding.
    """
    return raw.index(token) + len(token)


async def test_a_nested_vocabulary_refusal_is_keyed_by_its_json_path(
    client: httpx.AsyncClient,
) -> None:
    """The measured key, and the sentence that repeats it, byte for byte.

    Both are written out here rather than built from the module's own constants: a body compared
    with the template it was rendered from asserts nothing about the template.
    """
    errors = await _refusal(client, ONE_LINE)

    assert list(errors) == ["$.DeviceProfile.TranscodingProfiles[0].Protocol"]
    assert errors[NESTED_KEY] == [
        "The JSON value could not be converted to Jellyfin.Data.Enums.MediaStreamProtocol. "
        "Path: $.DeviceProfile.TranscodingProfiles[0].Protocol | LineNumber: 0 | "
        f"BytePositionInLine: {_token_ends_at(ONE_LINE, b'"dash"')}."
    ]


async def test_the_position_is_an_offset_into_the_body_and_not_into_the_token(
    client: httpx.AsyncClient,
) -> None:
    """The difference between the two shapes, asserted as a difference.

    `POST /Playlists` answers the same number for the same token wherever the property sits — `3`
    for a one-character token in a 62-byte body and in one twice as long. Here the number *is*
    where the token sits, so padding an earlier property moves it by exactly the padding
    `[probe: tools/probe_playback_info.py, Jellyfin 10.11.11, 2026-09-03]`.
    """
    padded = ONE_LINE.replace(b'"Container":"ts"', b'"Container":"ts,mp4,mkv,webm"')

    first = await _refusal(client, ONE_LINE)
    second = await _refusal(client, padded)

    assert first[NESTED_KEY] == [NESTED_MESSAGE.format(line=0, position=89)]
    assert second[NESTED_KEY] == [
        NESTED_MESSAGE.format(line=0, position=89 + len(b",mp4,mkv,webm"))
    ]
    assert _token_ends_at(ONE_LINE, b'"dash"') == 89


async def test_a_body_across_several_lines_is_counted_within_its_own_line(
    client: httpx.AsyncClient,
) -> None:
    """`LineNumber` is not always the `0` every measured body had.

    Both numbers are what a reader reports for the place it stopped, and the reference's own name
    for the second one — `BytePositionInLine` — says which of the two carries the newlines. No
    measured body had more than one line, so this row is the arithmetic and not a measurement.
    """
    errors = await _refusal(client, MANY_LINES)

    assert errors[NESTED_KEY] == [NESTED_MESSAGE.format(line=3, position=44)]
    assert MANY_LINES.split(b"\n")[3].index(b'"dash"') + len(b'"dash"') == 44


async def test_a_property_the_client_spelled_differently_is_still_found_in_the_bytes(
    client: httpx.AsyncClient,
) -> None:
    """The path is the model's spelling; the document is the client's, and they can differ.

    `compat/model.py` accepts any casing the reference accepts, so the token this offset points at
    sits under a key spelled `protocol` while the path reports `Protocol`. A reader matching keys
    case-sensitively would find nothing and fall back to the other shape's number, which is the
    one thing that would make the sentence disagree with the body it describes. Which spelling the
    *path* carries is 012 plan §6.6's rule — the alias, per level — and is measured on a body that
    spells them as the reference does.
    """
    lowered = ONE_LINE.replace(b'"Protocol"', b'"protocol"')

    errors = await _refusal(client, lowered)

    assert errors[NESTED_KEY] == [
        NESTED_MESSAGE.format(line=0, position=_token_ends_at(lowered, b'"dash"'))
    ]


def test_with_no_bytes_to_count_the_message_falls_back_to_the_other_shapes_number() -> None:
    """D-6's option (b), reached only where option (a) cannot run.

    The key and the path are what a client's error display shows and a bug report quotes, so they
    are produced whether or not the document is at hand; the integer is the one thing that needs
    the bytes. A caller with none — a query failure, or a test of the keying — gets the top-level
    rule's `len(token) + 2` rather than no sentence at all (012 plan §11, D-6).
    """
    failure = {
        "type": "enum",
        "loc": ["body", "device_profile", "transcoding_profiles", 0, "protocol"],
        "input": "dash",
    }

    keyed = validation_errors([failure], None, _Negotiation, None)

    assert keyed == {NESTED_KEY: [NESTED_MESSAGE.format(line=0, position=6)]}


def test_a_failure_one_level_deep_keeps_the_key_it_was_measured_with() -> None:
    """The rule that keeps every body 007 and 009 measured answering what it answered.

    `$` is the path of a top-level failure as `POST /Playlists` reports one, and this builder must
    not turn it into `$.UserId` — the same walk, one level shorter, and a different answer
    `[probe: tools/probe_playlist_creation.py, Jellyfin 10.11.11, 2026-08-31]`.
    """
    failure = {"type": "string_type", "loc": ["body", "user_id"], "input": 7}

    assert validation_errors([failure], None, _Negotiation, None) == {
        "": ["The supplied value is invalid."]
    }
