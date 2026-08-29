# SPDX-License-Identifier: GPL-3.0-or-later
"""The half of the four `stream` routes that has no process behind it: the original bytes.

`GET /Audio/{itemId}/stream[.{container}]` and `GET /Videos/{itemId}/stream[.{container}]` are two
controllers upstream and two modules here, and every line they would otherwise have shared lives in
this one - the item lookup, the range negotiation, the label, and the exact header set. A route
that built its own response would be a route that could seek differently from its sibling.

**`static=true` means the source bytes, absolutely.** Not "the source bytes if the container
matches": `stream.mkv?static=true` on an mp4 film is the mp4 bytes behind `Content-Type:
video/x-matroska`, and `stream.wav?static=true` on an m4a track is the m4a bytes behind
`audio/wav` - measured across every container `library/walker.py` admits
`[probe: tools/probe_range_matrix.py, Jellyfin 10.11.11, 2026-08-29]`, behaviours section 2.20.
The suffix picks the label and decides nothing else, which is what keeps a download working for
the client that names the wrong container.

**These routes require no token, and that is the implementation of a measured rule.** A request
carrying nothing at all, one carrying a token nothing issued, and one carrying `?api_key=` all
answer the identical `200` - on all four routes, and unlike `/Audio/{id}/universal`, which answers
`401` to the first two from the same probe run
`[probe: tools/probe_range_matrix.py, Jellyfin 10.11.11, 2026-08-29]`, `[source:
Jellyfin.Api/Controllers/AudioController.cs:89, Jellyfin.Api/Controllers/VideosController.cs:312,
Jellyfin.Api/Controllers/UniversalAudioController.cs:94 @ v10.11.11]` - the stream actions carry no
`[Authorize]` attribute where the universal one does. So there is no authentication dependency
here, the same shape and the same reason `api/images.py` has none: a route that declared one and
ignored its answer would still have to decide what an *invalid* token means, and a route that
declares none cannot get that wrong. The consequence is the one behaviours section 2.10 records
knowingly - **an item id is a capability** - and it is the reference's, not an invention.

**The measured header set is four headers, and no more** `[probe: tools/probe_range_matrix.py,
Jellyfin 10.11.11, 2026-08-29]`:

    Content-Length: 3275769255
    Content-Type: video/mp4
    Accept-Ranges: bytes
    Last-Modified: Sat, 14 Mar 2026 18:33:10 GMT

A `206` adds `Content-Range`; a `416` is that same set with `Content-Length: 0` and
`Content-Range: bytes */{size}`. There is **no `ETag`**, no `Content-Disposition`, no
`Cache-Control` and no conditional handling at all - a request whose `If-Modified-Since` is in the
future answers `200` with the whole film, measured. That is why the response is built by hand
rather than with the framework's file response, which ships a validator and a disposition the
reference does not send: 006 met the same trap on the image routes and this is the same answer.

See specs/008-playback-negotiation-and-delivery/spec.md section 3.5 and plan section 6.5.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from email.utils import format_datetime
from pathlib import Path

from fastapi import Request
from starlette.responses import Response, StreamingResponse

from atrium.api.deps import get_sessions
from atrium.compat.errors import DeliveryNotFoundError
from atrium.compat.ranges import RangeAnswer, negotiate_range
from atrium.db.engine import session_scope
from atrium.db.repositories import MediaFileRepository
from atrium.media.labels import label_for

#: How much is read from disk at a time. Large enough that a film is not a million syscalls, small
#: enough that a cancelled response stops promptly - a client that seeks abandons the body it was
#: reading, and 008's kill paths depend on that being noticed quickly (spec section 3.8).
CHUNK_BYTES = 64 * 1024

#: The `Range` unit and the fixed value of the header that advertises it. A body whose size is
#: known always carries this, which is AC-11.
ACCEPT_RANGES = "bytes"

#: What a container may be spelled with, **verbatim as the reference declares it** on every
#: container parameter of every delivery route `[source:
#: MediaBrowser.Controller/MediaEncoding/EncodingHelper.cs:41 @ v10.11.11]`. A spelling outside it
#: is a validation `400` keyed on `container`, and the refusal happens before the item is even
#: looked up: an unknown item asked for through a bad container answers the `400`, not the `404`
#: `[probe: tools/probe_range_matrix.py, Jellyfin 10.11.11, 2026-08-29]`. Declared as a pattern
#: rather than checked in a handler so the refusal is the framework's, which is what makes it the
#: same problem-details body every other bad parameter in this project produces.
CONTAINER_PATTERN = r"^[a-zA-Z0-9\-\._,|]{0,40}$"


def static_response(request: Request, item_id: str, container: str | None) -> Response:
    """One `static=true` answer, for either route family.

    The container is the path's suffix, or `None` on the unsuffixed form - and in both cases the
    bytes are the file's. `container` also arrives as a query parameter on the unsuffixed route
    and means the same thing there, measured.
    """
    with session_scope(get_sessions(request)) as opened:
        found = MediaFileRepository(opened).locate(item_id)

    absolute = None if found is None else found.absolute_path()
    if found is None or absolute is None:
        raise DeliveryNotFoundError
    try:
        stat = Path(absolute).stat()
    except OSError as error:
        # The item exists and its file does not - a removed or unreadable file between two scans.
        # The reference's answer to this is not measured (it would need a file deleted underneath
        # a live server), so this takes the refusal it *is* measured to send when it cannot serve
        # an item's bytes rather than inventing a fifth shape.
        raise DeliveryNotFoundError from error

    answer = negotiate_range(request.headers.get("range"), stat.st_size)
    return _ranged(
        absolute,
        answer,
        media_type=label_for(container, found.relative_path),
        last_modified=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
    )


def _ranged(
    path: str, answer: RangeAnswer, *, media_type: str, last_modified: datetime
) -> Response:
    """The measured header set, and the bytes the answer names.

    The headers are written in the order the reference sends them and **built explicitly**: every
    one of the four was read off a live response, and the two the framework would have added on
    its own - an `ETag` and a `Content-Disposition` - are absent from the reference and therefore
    absent here.
    """
    headers = {
        "Content-Length": str(answer.length),
        "Content-Type": media_type,
        "Accept-Ranges": ACCEPT_RANGES,
    }
    content_range = answer.content_range
    if content_range is not None:
        headers["Content-Range"] = content_range
    headers["Last-Modified"] = format_datetime(last_modified.astimezone(UTC), usegmt=True)

    if answer.is_refusal:
        # A `416` carries the whole set with nothing behind it, measured - including the
        # `Content-Type` of the body it declined to send.
        return Response(status_code=answer.status, headers=headers)
    return StreamingResponse(
        _bytes_of(path, answer.start, answer.length),
        status_code=answer.status,
        headers=headers,
    )


def _bytes_of(path: str, start: int, length: int) -> Iterator[bytes]:
    """Exactly `length` bytes from `start`, read in blocks and never held whole.

    A film is gigabytes and the response is a slice of it; reading the file into memory to answer
    `bytes=100-199` would be the same mistake at every scale.
    """
    if length <= 0:
        return
    with Path(path).open("rb") as handle:
        handle.seek(start)
        remaining = length
        while remaining > 0:
            block = handle.read(min(CHUNK_BYTES, remaining))
            if not block:
                # The file shrank under us. Stopping short truncates the body against the
                # `Content-Length` already sent, which is the same thing the reference does and is
                # what the client sees as a dropped connection.
                break
            remaining -= len(block)
            yield block


__all__ = ["ACCEPT_RANGES", "CHUNK_BYTES", "CONTAINER_PATTERN", "static_response"]
