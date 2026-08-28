# SPDX-License-Identifier: GPL-3.0-or-later
"""`GET /Items/{itemId}/Images/{imageType}` and its indexed form.

The wire, and only the wire: parsing, headers, the conditional pair and the two refusal statuses.
Everything that decides what the bytes are lives in `images/`, and a test asserts that neither
package can reach into the other (006 plan section 3).

**No authentication dependency at all**, and that is the implementation of the rule rather than an
oversight. The reference answers this route `200` with no token, with every one of 002 section
3.1's mechanisms, and with an unknown or malformed token
`[probe: tools/probe_auth_mechanisms.py, Jellyfin 10.11.11, 2026-08-26]`
`[probe: manual requests via tools/_probe.py, Jellyfin 10.11.11, 2026-08-28]`. A route that
declared a dependency and ignored its answer would still have to decide what an *invalid* token
means; a route that declares none cannot get that wrong. The consequence is recorded knowingly:
**an item id is a capability** here (spec section 3.2, behaviours section 2.10).

**Plain `Response` objects, with the header set built explicitly.** Starlette's `FileResponse`
computes an `ETag` on every response and the measured reference sends none at all - so the
convenient class is the one that ships a validator the reference does not have, on every image.
The sweep in `tests/conformance/test_image_routes.py` asserts the set exactly, absences included,
so a framework upgrade that starts adding one fails a test instead of shipping a delta.

The measured `200` set, reproduced here `[probe: manual requests via tools/_probe.py, Jellyfin
10.11.11, 2026-08-28]`:

    Content-Type: image/jpeg
    Content-Length: 84351
    Last-Modified: Tue, 11 Aug 2026 16:44:10 GMT
    Cache-Control: public                       (public, max-age=31536000 with a `tag`)
    Vary: Accept
    Content-Disposition: attachment
    transferMode.dlna.org: Interactive
    realTimeInfo.dlna.org: DLNA.ORG_TLAG=*

`Server` and `X-Response-Time-ms` arrive from 001's middleware like everywhere else. A `304` is
that set minus `Content-Length`, measured.
"""

from __future__ import annotations

from datetime import UTC, datetime
from email.utils import format_datetime, parsedate_to_datetime
from enum import StrEnum
from typing import Annotated

from fastapi import APIRouter, Query, Request, Response
from pydantic import BeforeValidator

from atrium.api.deps import get_paths, get_sessions
from atrium.compat.guids import WireGuid
from atrium.compat.query_params import IgnoredParameters, known_tokens
from atrium.db.engine import session_scope
from atrium.db.repositories import ImageRepository
from atrium.images.cache import DIRECTORY, ImageCache
from atrium.images.service import ImageQuery, ImageReply, ImageService
from atrium.images.transform import RequestedFormat

router = APIRouter()

UNINDEXED = "/Items/{itemId}/Images/{imageType}"
INDEXED = "/Items/{itemId}/Images/{imageType}/{imageIndex}"


class ImageTypeToken(StrEnum):
    """The reference's `ImageType`, **all thirteen members** `[spec: ImageType]`.

    Not the eight of spec section 3.2, and the difference is the error table: a string outside
    this vocabulary is a `400`, while `Box` - a member no v1 writer creates - is a `404` naming
    the item and the type `[probe: tools/probe_image_formats.py, Jellyfin 10.11.11, 2026-08-28]`.
    Parsing against the eight would answer `400` where the reference answers `404`.
    """

    PRIMARY = "Primary"
    ART = "Art"
    BACKDROP = "Backdrop"
    BANNER = "Banner"
    LOGO = "Logo"
    THUMB = "Thumb"
    DISC = "Disc"
    BOX = "Box"
    SCREENSHOT = "Screenshot"
    MENU = "Menu"
    CHAPTER = "Chapter"
    BOX_REAR = "BoxRear"
    PROFILE = "Profile"


_BY_FOLDED = {member.value.lower(): member.value for member in ImageTypeToken}


def _canonical_type(value: object) -> object:
    """Match the vocabulary case-insensitively, because this arrives as a **path segment**.

    Paths match case-insensitively as a rule (behaviours section 1.14) and the type is a segment
    of one, so `/images/primary` is the same request as `/Images/Primary`. Anything that is not a
    member is left alone for the enum to reject, which is what produces the measured `400` with
    the value quoted in `errors`.
    """
    if isinstance(value, str):
        return _BY_FOLDED.get(value.lower(), value)
    return value


#: Lenient in, canonical out - the same shape `WireGuid` uses for identifiers.
WireImageType = Annotated[ImageTypeToken, BeforeValidator(_canonical_type)]

#: What rides on every image response, `304`s included. Constants rather than a helper's opinion:
#: each one was read off a live response, and a header nobody can explain is a header nobody
#: should be inventing.
CONSTANT_HEADERS = {
    "Content-Disposition": "attachment",
    "transferMode.dlna.org": "Interactive",
    "realTimeInfo.dlna.org": "DLNA.ORG_TLAG=*",
    "Vary": "Accept",
}

#: Measured verbatim, both values. Only the `tag` makes a URL immutable, so only a tagged request
#: gets the year.
CACHE_CONTROL_BARE = "public"
CACHE_CONTROL_TAGGED = "public, max-age=31536000"

#: The token whose presence in `Accept` changes the answer (plan section 6.4). Read as a substring
#: of the header rather than by parsing it: the reference negotiates on the token being offered at
#: all, and a q-value parser here would be a guess dressed as rigour.
WEBP_TOKEN = "image/webp"  # noqa: S105 - a media type, not a credential


def _cache(request: Request) -> ImageCache:
    """One per application, which is what makes the unwritable-cache warning once per process."""
    existing: ImageCache | None = getattr(request.app.state, "image_cache", None)
    if existing is None:
        existing = ImageCache(get_paths(request).cache / DIRECTORY)
        request.app.state.image_cache = existing
    return existing


def _recorder(request: Request) -> IgnoredParameters:
    ignored: IgnoredParameters = request.app.state.ignored_parameters
    return ignored


def _format_of(value: str | None, route: str, ignored: IgnoredParameters) -> RequestedFormat | None:
    """`format`, parsed leniently: a token outside the vocabulary is dropped and counted.

    Measured: `format=Banana` answers `200` with the value ignored, which is behaviours section
    1.12's shape and **not** the `400` the dimension parameters get. The collision between the two
    rules is real and the measurement settles it
    `[probe: tools/probe_image_formats.py, Jellyfin 10.11.11, 2026-08-28]`.
    """
    if value is None:
        return None
    found = known_tokens([value], RequestedFormat, route=route, parameter="format", ignored=ignored)
    return found[0] if found else None


def _since(request: Request) -> datetime | None:
    """`If-Modified-Since`, parsed leniently. An unreadable date is ignored.

    Measured: `If-Modified-Since: banana` answers `200` rather than refusing, which is the
    ordinary HTTP reading and the lenient one either way
    `[probe: manual requests via tools/_probe.py, Jellyfin 10.11.11, 2026-08-28]`.
    """
    raw = request.headers.get("if-modified-since")
    if not raw:
        return None
    try:
        parsed = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _headers(reply: ImageReply, tag: str | None) -> dict[str, str]:
    """The explicit set, `200` and `304` alike. `Content-Length` is Starlette's, from the body -
    and it omits one on a `304`, which is what the measurement shows."""
    return {
        "Last-Modified": format_datetime(reply.last_modified.astimezone(UTC), usegmt=True),
        "Cache-Control": CACHE_CONTROL_TAGGED if tag else CACHE_CONTROL_BARE,
        **CONSTANT_HEADERS,
    }


def _unmodified(sent: datetime | None, last_modified: datetime) -> bool:
    """Whole seconds, both sides. `Last-Modified` is sent with second precision, so comparing a
    filesystem's nanoseconds against it would answer `200` to a client echoing back exactly what
    the server told it."""
    if sent is None:
        return False
    return int(last_modified.timestamp()) <= int(sent.timestamp())


def _answer(reply: ImageReply, tag: str | None) -> Response:
    """The `200`: the payload, its own type, and the explicit header set.

    `Content-Length` is Starlette's, from the body - the payload is complete by contract (plan
    section 5), so the two can never disagree.
    """
    return Response(
        content=reply.payload, media_type=reply.media_type, headers=_headers(reply, tag)
    )


def _not_modified(reply: ImageReply, tag: str | None) -> Response:
    """The `200`'s header set minus `Content-Length`, measured - the DLNA pair included and the
    **resolved** `Content-Type` with them.

    That last part is why this takes a whole `ImageReply` rather than a date. Plan section 6.6
    asked for the conditional check to run "before any bytes are read", and for the `304` to carry
    the `200`'s header set: those two cannot both hold, because the `200`'s `Content-Type` is a
    property of the payload that would have been sent. The reference resolves it too - a
    conditional request offering `image/webp` on a resized image answers `304` with
    `Content-Type: image/webp`, and the same request without the offer answers `image/jpeg`
    `[probe: manual requests via tools/_probe.py, Jellyfin 10.11.11, 2026-08-28]`. So the answer is
    computed and the body is dropped, which after the first request is a cache read rather than an
    encode.
    """
    return Response(status_code=304, media_type=reply.media_type, headers=_headers(reply, tag))


def _serve(
    request: Request,
    route: str,
    item_id: str,
    image_type: ImageTypeToken,
    index: int,
    *,
    max_width: int | None,
    max_height: int | None,
    width: int | None,
    height: int | None,
    fill_width: int | None,
    fill_height: int | None,
    quality: int | None,
    image_format: str | None,
    tag: str | None,
) -> Response:
    """One body for both routes: the indexed form differs only in where the index came from."""
    ignored = _recorder(request)
    query = ImageQuery(
        item_id=item_id,
        image_type=image_type.value,
        index=index,
        max_width=max_width,
        max_height=max_height,
        width=width,
        height=height,
        fill_width=fill_width,
        fill_height=fill_height,
        quality=quality,
        image_format=_format_of(image_format, route, ignored),
        accepts_webp=WEBP_TOKEN in request.headers.get("accept", "").lower(),
    )

    with session_scope(get_sessions(request)) as opened:
        service = ImageService(ImageRepository(opened), _cache(request), get_paths(request).root)
        # The two refusals come first, because a request for an image that is not there is not
        # "unmodified" - the conditional header cannot turn a `404` into a `304`.
        reply = service.get(query)

    for parameter in reply.dropped:
        ignored.record(route, parameter)
    if _unmodified(_since(request), reply.last_modified):
        return _not_modified(reply, tag)
    return _answer(reply, tag)


@router.get(UNINDEXED)
async def get_item_image(
    request: Request,
    itemId: WireGuid,  # noqa: N803 - the reference's spellings, throughout
    imageType: WireImageType,  # noqa: N803
    maxWidth: Annotated[int | None, Query()] = None,  # noqa: N803
    maxHeight: Annotated[int | None, Query()] = None,  # noqa: N803
    width: Annotated[int | None, Query()] = None,
    height: Annotated[int | None, Query()] = None,
    fillWidth: Annotated[int | None, Query()] = None,  # noqa: N803
    fillHeight: Annotated[int | None, Query()] = None,  # noqa: N803
    quality: Annotated[int | None, Query()] = None,
    format: Annotated[str | None, Query()] = None,  # noqa: A002 - the reference's spelling
    tag: Annotated[str | None, Query()] = None,
    imageIndex: Annotated[int | None, Query()] = None,  # noqa: N803
) -> Response:
    """`GetItemImage` `[spec: GetItemImage]`.

    **No range constraints on the dimensions.** `maxWidth=-100` must parse and be forgiven with
    `200` (measured), so a `ge=0` bound would manufacture a `400` the reference does not send.
    The five decoration parameters - `percentPlayed`, `unplayedCount`, `blur`, `backgroundColor`,
    `foregroundLayer` - stay **undeclared** on purpose: they are the spec's declared v1 gap, and
    an undeclared parameter is exactly what the ignored-parameter recorder counts, which is how
    OQ-4 gets a measurable trail without a line of image code.

    `imageIndex` is declared as a *query* parameter here as well, because the pinned document does
    `[spec: GetItemImage]` and the reference honours it - measured on an item whose backdrops
    differ `[probe: manual requests via tools/_probe.py, Jellyfin 10.11.11, 2026-08-28]`.
    """
    return _serve(
        request,
        UNINDEXED,
        itemId,
        imageType,
        imageIndex or 0,
        max_width=maxWidth,
        max_height=maxHeight,
        width=width,
        height=height,
        fill_width=fillWidth,
        fill_height=fillHeight,
        quality=quality,
        image_format=format,
        tag=tag,
    )


@router.get(INDEXED)
async def get_item_image_by_index(
    request: Request,
    itemId: WireGuid,  # noqa: N803
    imageType: WireImageType,  # noqa: N803
    imageIndex: int,  # noqa: N803
    maxWidth: Annotated[int | None, Query()] = None,  # noqa: N803
    maxHeight: Annotated[int | None, Query()] = None,  # noqa: N803
    width: Annotated[int | None, Query()] = None,
    height: Annotated[int | None, Query()] = None,
    fillWidth: Annotated[int | None, Query()] = None,  # noqa: N803
    fillHeight: Annotated[int | None, Query()] = None,  # noqa: N803
    quality: Annotated[int | None, Query()] = None,
    format: Annotated[str | None, Query()] = None,  # noqa: A002
    tag: Annotated[str | None, Query()] = None,
) -> Response:
    """`GetItemImageByIndex` `[spec: GetItemImageByIndex]`. The same body, one segment further."""
    return _serve(
        request,
        INDEXED,
        itemId,
        imageType,
        imageIndex,
        max_width=maxWidth,
        max_height=maxHeight,
        width=width,
        height=height,
        fill_width=fillWidth,
        fill_height=fillHeight,
        quality=quality,
        image_format=format,
        tag=tag,
    )


__all__ = [
    "CACHE_CONTROL_BARE",
    "CACHE_CONTROL_TAGGED",
    "CONSTANT_HEADERS",
    "INDEXED",
    "UNINDEXED",
    "ImageTypeToken",
    "WireImageType",
    "router",
]
