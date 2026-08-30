# SPDX-License-Identifier: GPL-3.0-or-later
"""The reference's `SubtitleController`: one track, one format, one window - and the windows.

Three routes and two behaviours. `GET …/Subtitles/{index}/Stream.{format}` names the window in its
query; `GET …/Subtitles/{index}/{startPositionTicks}/Stream.{format}` names its start in the path
instead, and it is the form a **negotiation's own `DeliveryUrl`** points at, so a client following
the address it was handed lands there rather than on the other one (011 spec section 3.5). The
reference implements the second by calling the first, and so does this. `GET
…/Subtitles/{index}/subtitles.m3u8` is the third, and it is a different animal: it addresses the
other two rather than answering cues, and it shares none of their rules.

**Neither fetch route requires a caller**, measured: no token, an unknown token and `?ApiKey=`
answer the identical `200` with the cues, where the subtitle *playlist* beside them refuses both
of the first two with an empty `401` `[probe: tools/probe_subtitle_delivery.py, Jellyfin 10.11.11,
2026-08-29]`. That is the same per-action split behaviours section 2.10 records for the four
`stream` routes, extended to two more - so the item is resolved by identifier alone, with no
visibility predicate, exactly as `api/delivery.py` resolves it.

## The playlist is the negotiation's shapes, not the delivery routes'

It wants a caller, it resolves the item **through 005's visibility query**, and every one of its
refusals differs from the fetch routes' for the same condition (spec section 3.7). Three of them
are worth naming here because a reader who knows the fetch column will guess wrong:

* an identifier nothing holds is the problem-details `404`, where the fetch routes answer `400`
  in `text/plain`;
* an item that **is** there and is not a video - a series, an audio track - is that same `404`,
  where the fetch routes answer `500`. The reference's own lookup asks for a video and hands the
  framework's not-found result back for anything else `[source:
  Jellyfin.Api/Controllers/SubtitleController.cs:350-354 @ v10.11.11]`, measured on a series
  identifier in one run beside the fetch route's `500` for the same one
  `[probe: tools/probe_subtitle_delivery.py, Jellyfin 10.11.11, 2026-08-30]`;
* an identifier that is not an identifier at all names **`itemId`** in its problem details, where
  the fetch routes name `routeItemId` - because each route names its own path segment and the two
  spell it differently. Measured in the same run.

**And it never reads the index it is given.** The reference's own declaration marks that parameter
unused, so a playlist for a stream that does not exist is a `200` listing every window, each of
which answers `500` when it is followed. Reproduced rather than improved: the whole surface of
this feature is a client following addresses it was handed, and a `404` here would refuse a
request the reference serves. What catches the failure that matters - a playlist that is well
formed and leads nowhere - is AC-8's traversal, which follows the addresses rather than reading
them.

## The four things the fetch routes do that no format specification predicts

**`js` is `json`, mapped before anything else**, which is the reference's own first act on the
format it was handed `[source: Jellyfin.Api/Controllers/SubtitleController.cs:231-234 @
v10.11.11]`. Everything after this point sees `json`, including the label lookup - which is why
`Stream.js` answers `application/json` and not something of its own.

**The deprecated query parameters beat the address.** `itemId`, `mediaSourceId`, `index` and
`format` are declared obsolete on the reference and are still bound, and each **overrides** the
route value beside it: `Stream.vtt?format=srt` answers SubRip under `application/x-subrip`, and
`Stream.vtt?index=99` answers the `500` a missing stream answers `[probe:
tools/probe_subtitle_delivery.py, Jellyfin 10.11.11, 2026-08-30]`. A route that bound only its
path would answer a different track to a client that sends one, so they are bound here.

**The start position in the query beats the one in the path**, on the route that has both -
`…/6000000000/Stream.vtt?StartPositionTicks=0` answers the track from its first cue, measured in
the same run. Plan section 6.7 had the direction the other way round.

**Asking for the format the track is already in answers the whole track.** The reference returns
the readable file before it parses anything, so the window and both timestamp switches are
ignored `[source: MediaBrowser.MediaEncoding/Subtitles/SubtitleEncoder.cs:144-155 @ v10.11.11]` -
measured on both routes, where `Stream.srt?StartPositionTicks=…&EndPositionTicks=…` on a SubRip
track answers the same 84 858 bytes as the unwindowed request. It is unreachable from a playlist,
whose entries always name `stream.vtt`, and one request away by hand. Reproduced, because what it
hands back is a real answer a real client can ask for - and because the artefact it hands back is
not what ffmpeg wrote (`media/extract.py`).

## What the fetch routes answer when they will not answer cues

Two shapes at two statuses, both `text/plain` with the fixed twenty-five bytes, split by what
failed - which is the reference's exception map rather than a design here: an `ArgumentException`
is a `400` and everything else is a `500` `[source:
Jellyfin.Api/Middleware/ExceptionMiddleware.cs:123-136 @ v10.11.11]`. So an item that names
nothing is a `400` and a **media source** that names nothing is a `500`, which is the opposite way
round from the same pair on 008's delivery routes (spec section 3.7, `compat/errors.py`) - and an
item that **is** there with nothing servable on it, a series or an audio track, is the `500` as
well, which is why the lookup asks whether the item exists before it asks for its parts.

**None of the three answers `Accept-Ranges`**, none answers `Last-Modified` or an `ETag`, and a
`Range` header is ignored: the whole measured header set is `Content-Type` and `Content-Length`
on the two fetch routes and on the playlist alike `[probe: tools/probe_subtitle_delivery.py,
Jellyfin 10.11.11, 2026-08-30]`. That is the same absence 008 T14 found on the two HLS
playlists, on three more routes.

See specs/011-subtitle-delivery/spec.md sections 3.5 and 3.7, and plan sections 6.6 and 6.7.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from starlette.responses import Response

from atrium.api.delivery import inspection_of, production_ledger
from atrium.api.deps import get_paths, get_sessions, require_user
from atrium.api.item_dto import VIDEO_TYPES
from atrium.compat.auth import extract_token
from atrium.compat.errors import (
    DeliveryProductionError,
    NotFoundError,
    SubtitleRequestError,
    SubtitleUnavailableError,
)
from atrium.compat.guids import WireGuid
from atrium.db.engine import session_scope
from atrium.db.item_queries import ItemQueryRepository
from atrium.db.repositories import MediaFileRepository
from atrium.domain.media import DeliveredFile, InspectedStream, MediaInspection, StreamKind
from atrium.domain.queries import ItemQuery
from atrium.domain.user import User
from atrium.media import extract, ffmpeg, hls, subtitles
from atrium.media.info import source_id
from atrium.media.labels import DEFAULT_MEDIA_TYPE, media_type_of

router = APIRouter(tags=["Subtitle"])

WITHOUT_TICKS = (
    "/Videos/{routeItemId}/{routeMediaSourceId}/Subtitles/{routeIndex}/Stream.{routeFormat}"
)
WITH_TICKS = (
    "/Videos/{routeItemId}/{routeMediaSourceId}/Subtitles/{routeIndex}"
    "/{routeStartPositionTicks}/Stream.{routeFormat}"
)

#: The playlist declares its path parameters under the reference's own spellings, which are
#: **not** the fetch routes' - and that is observable, because a value that will not bind is
#: refused by name (module docstring). `surface.yaml` already carried these three.
PLAYLIST = "/Videos/{itemId}/{mediaSourceId}/Subtitles/{index}/subtitles.m3u8"

#: What the playlist is labelled, from the one table `media/labels.py` holds - the same row 008's
#: two playlists read, measured identical on this route `[probe:
#: tools/probe_subtitle_delivery.py, Jellyfin 10.11.11, 2026-08-30]`.
PLAYLIST_MEDIA_TYPE = media_type_of("m3u8") or DEFAULT_MEDIA_TYPE

#: The reference's `Guid.Empty`, refused by a guard **before** any lookup runs `[source:
#: Emby.Server.Implementations/Library/LibraryManager.cs:1357-1361 @ v10.11.11]`. That guard is
#: why this identifier and one that merely names nothing answer differently on the playlist route
#: - `400` in the controller's shape against a problem-details `404` - where the fetch routes
#: collapse the two into one `400` because both of theirs are that shape anyway (measured).
EMPTY_IDENTIFIER = "0" * 32

#: The reference's own alias, mapped before the format reaches anything else.
JSON_ALIAS = {"js": "json"}


@router.get(WITHOUT_TICKS)
async def get_subtitle(
    request: Request,
    routeItemId: WireGuid,  # noqa: N803 - the reference's spellings, throughout
    routeMediaSourceId: str,  # noqa: N803
    routeIndex: int,  # noqa: N803
    routeFormat: str,  # noqa: N803
    itemId: Annotated[WireGuid | None, Query(deprecated=True)] = None,  # noqa: N803
    mediaSourceId: Annotated[str | None, Query(deprecated=True)] = None,  # noqa: N803
    index: Annotated[int | None, Query(deprecated=True)] = None,
    format: Annotated[str | None, Query(deprecated=True)] = None,  # noqa: A002 - the wire's name
    endPositionTicks: Annotated[int | None, Query()] = None,  # noqa: N803
    copyTimestamps: Annotated[bool, Query()] = False,  # noqa: N803
    addVttTimeMap: Annotated[bool, Query()] = False,  # noqa: N803
    startPositionTicks: Annotated[int, Query()] = 0,  # noqa: N803
) -> Response:
    """`GetSubtitle` `[spec: GetSubtitle]`: one track, converted, whole or windowed.

    **No authentication dependency**, which is the measured rule and not an omission (see the
    module docstring). The four deprecated query parameters are bound because the reference binds
    them and honours them over the path.
    """
    return await _serve(
        request,
        item_id=itemId or routeItemId,
        media_source_id=mediaSourceId or routeMediaSourceId,
        index=routeIndex if index is None else index,
        requested=format or routeFormat,
        start_ticks=startPositionTicks,
        end_ticks=endPositionTicks or 0,
        copy_timestamps=copyTimestamps,
        add_vtt_time_map=addVttTimeMap,
    )


@router.get(WITH_TICKS)
async def get_subtitle_with_ticks(
    request: Request,
    routeItemId: WireGuid,  # noqa: N803
    routeMediaSourceId: str,  # noqa: N803
    routeIndex: int,  # noqa: N803
    routeStartPositionTicks: int,  # noqa: N803
    routeFormat: str,  # noqa: N803
    itemId: Annotated[WireGuid | None, Query(deprecated=True)] = None,  # noqa: N803
    mediaSourceId: Annotated[str | None, Query(deprecated=True)] = None,  # noqa: N803
    index: Annotated[int | None, Query(deprecated=True)] = None,
    startPositionTicks: Annotated[int | None, Query(deprecated=True)] = None,  # noqa: N803
    format: Annotated[str | None, Query(deprecated=True)] = None,  # noqa: A002
    endPositionTicks: Annotated[int | None, Query()] = None,  # noqa: N803
    copyTimestamps: Annotated[bool, Query()] = False,  # noqa: N803
    addVttTimeMap: Annotated[bool, Query()] = False,  # noqa: N803
) -> Response:
    """`GetSubtitleWithTicks` `[spec: GetSubtitleWithTicks]`: the same answer, start in the path.

    **The query wins where both state a start**, measured - which is the opposite of the direction
    plan section 6.7 stated, and the reference's own `startPositionTicks ?? routeStartPositionTicks`
    `[source: Jellyfin.Api/Controllers/SubtitleController.cs:312-325 @ v10.11.11]`.
    """
    return await _serve(
        request,
        item_id=itemId or routeItemId,
        media_source_id=mediaSourceId or routeMediaSourceId,
        index=routeIndex if index is None else index,
        requested=format or routeFormat,
        start_ticks=(routeStartPositionTicks if startPositionTicks is None else startPositionTicks),
        end_ticks=endPositionTicks or 0,
        copy_timestamps=copyTimestamps,
        add_vtt_time_map=addVttTimeMap,
    )


@router.get(PLAYLIST)
async def get_subtitle_playlist(
    request: Request,
    caller: Annotated[User, Depends(require_user)],
    itemId: WireGuid,  # noqa: N803 - this route's own spellings, which are not the fetch routes'
    mediaSourceId: str,  # noqa: N803
    index: int,
    segmentLength: int,  # noqa: N803 - required, so an absent one is the framework's refusal
) -> Response:
    """`GetSubtitlePlaylist` `[spec: GetSubtitlePlaylist]`: one track's windows across a runtime.

    `index` is declared and **not read**, which is the reference's own shape and the module
    docstring's last paragraph. It is bound as an `int` because the reference binds it as one, so
    `Subtitles/abc/subtitles.m3u8` is the framework's problem details naming it - and a negative
    one, or one naming no stream at all, is a full playlist.

    `segmentLength` has no default: the reference marks it required, so an absent or unparseable
    one is problem details naming it rather than a playlist at some assumed length (measured).

    The two refusals the route raises itself are `400` in the controller's shape, and they are
    checked in the reference's order - the source's runtime first, then the window length
    `[source: Jellyfin.Api/Controllers/SubtitleController.cs:356-369 @ v10.11.11]`. Both are
    `ArgumentException` there, which is the one type its middleware maps to `400`.
    """
    runtime_ticks = _runtime_of(request, caller, itemId, mediaSourceId)
    if runtime_ticks <= 0 or segmentLength <= 0:
        raise SubtitleRequestError
    body = hls.subtitle_playlist(runtime_ticks, segmentLength, extract_token(request))
    return Response(content=body, media_type=PLAYLIST_MEDIA_TYPE)


def _runtime_of(request: Request, caller: User, item_id: str, media_source_id: str) -> int:
    """How long the named part of the named item is, or one of this route's two `404`s.

    **Resolved through 005's visibility query**, which is why an unknown item and an invisible one
    are one problem-details `404` here where the fetch routes answer `400` in `text/plain` for the
    first and serve the second. The reference resolves it with the user for the same reason.

    The **type** test is the second half of that lookup and not an extra: the reference asks for a
    video, so a series identifier and an audio track are the same `404` as an identifier nothing
    holds - measured, and the opposite of the fetch routes' `500` for the same two.

    A `mediaSourceId` naming no part is the `500`, which is `_part_named`'s answer and the
    reference's null source dereferenced one line later. A runtime of zero is **not** refused
    here: it is the caller's `400`, beside the window length it shares a shape with.
    """
    if item_id == EMPTY_IDENTIFIER:
        # Before the lookup, because the reference's guard is before its lookup - and the order is
        # observable here in a way it is not on the fetch routes: this identifier is the `400` and
        # an identifier that merely names nothing is the `404` below.
        raise SubtitleRequestError
    with session_scope(get_sessions(request)) as opened:
        page = ItemQueryRepository(opened).run(
            ItemQuery(user=caller, ids=(item_id,), limit=1, count=False)
        )
    if not page.items:
        raise NotFoundError
    found = page.items[0]
    if found.item.type not in VIDEO_TYPES:
        raise NotFoundError
    part_index = _part_named(
        tuple(part.relative_path for part in found.item.sources), item_id, media_source_id
    )
    inspection = found.probes[part_index] if part_index < len(found.probes) else None
    # A part nothing has inspected states no runtime, which is the same zero as an inspection that
    # read one and found none - and the reference's own `RunTimeTicks ?? -1` collapses them too.
    return 0 if inspection is None else (inspection.runtime_ticks or 0)


async def _serve(
    request: Request,
    *,
    item_id: str,
    media_source_id: str,
    index: int,
    requested: str,
    start_ticks: int,
    end_ticks: int,
    copy_timestamps: bool,
    add_vtt_time_map: bool,
) -> Response:
    """The whole of both routes.

    The order is the reference's, with one step brought forward: **the format is checked before
    any file is opened**. There, an unwritable format is refused by the writer lookup *after* the
    extraction has run, so `Stream.xyz` on a track nothing has extracted yet pays for a demux
    before its `400`. The status and the twenty-five bytes are identical either way; what differs
    is the latency, which is the same trade plan section 6.7 takes for an image track.
    """
    canonical = JSON_ALIAS.get(requested.lower(), requested.lower())
    if canonical not in subtitles.WRITABLE:
        raise SubtitleRequestError

    found = _located(request, item_id, media_source_id)
    inspection = _inspected(request, found)
    stream = _stream_named(inspection, index)

    raw, current = await _readable(request, found, inspection, stream)

    # The label is the requested format's own row and never the media file's, so a track asked
    # for under a spelling `media/labels.py` has no row for falls all the way to the default -
    # which is what `Stream.subrip` and `Stream.webvtt` are measured to answer.
    label = media_type_of(canonical) or DEFAULT_MEDIA_TYPE

    if canonical == current.lower():
        return _answer(raw, label)

    try:
        cues = subtitles.parse(extract.as_text(raw), current)
    except ValueError as error:
        # A document nothing can parse, and a document that parses to no cues at all: both are the
        # reference's `ArgumentException`, so both are the `400` (module docstring).
        raise SubtitleRequestError from error
    except ffmpeg.ProductionError as error:
        raise SubtitleUnavailableError from error

    selected = subtitles.window(
        cues, start_ticks=start_ticks, end_ticks=end_ticks, copy_timestamps=copy_timestamps
    )
    # `requested` and not `canonical`: the time map switch is read against the spelling `vtt`
    # alone, so `Stream.webvtt?AddVttTimeMap=true` answers a plain document with its byte order
    # mark intact - measured (`media/subtitles.py`).
    body = subtitles.render(selected, requested, add_vtt_time_map=add_vtt_time_map)
    return _answer(body, label)


def _located(request: Request, item_id: str, media_source_id: str) -> DeliveredFile:
    """The part this request is about, refused the way **these** routes refuse.

    Not `api/delivery.py`'s `locate`, and the reason is the order it asks its two questions in.
    Both of the refusals here are the other way round from that route's - an item that names
    nothing is a `400` where it is the third-shape `404` there, and a `mediaSourceId` that names
    nothing is a `500` where it is a `400` there - and **the item is asked about first**, because
    the difference between the two statuses is *whether the item is there at all*:

    * an identifier nothing holds, the all-zero form included, is a `400`: the reference hands a
      null item to a null check and its middleware maps that to `400`;
    * an item that **is** here and has nothing servable is a `500` - measured on a series
      identifier and on an audio track in one run, both of which reach a lookup over an empty
      sequence `[probe: tools/probe_subtitle_delivery.py, Jellyfin 10.11.11, 2026-08-30]`.

    Asking for the part first would collapse the two, because an item with no source and an item
    that is not there both have no parts.
    """
    with session_scope(get_sessions(request)) as opened:
        repository = MediaFileRepository(opened)
        if not repository.present(item_id):
            raise SubtitleRequestError
        part_index = _part_named(repository.parts(item_id), item_id, media_source_id)
        found = repository.locate(item_id, part_index)
    if found is None:
        raise SubtitleUnavailableError
    return found


def _part_named(paths: tuple[str, ...], item_id: str, media_source_id: str) -> int:
    """Which part the identifier names, or the `500` when it names none.

    The identifiers are derived rather than stored, through `media/info.py`'s one derivation -
    the same one `api/delivery.py` compares against, so a source a client can address on a
    delivery route is addressable here under the same string.
    """
    wanted = media_source_id.strip().lower()
    for index, relative_path in enumerate(paths):
        if source_id(item_id, index, relative_path).lower() == wanted:
            return index
    raise SubtitleUnavailableError


def _inspected(request: Request, found: DeliveredFile) -> MediaInspection:
    """What was stored about this file. A source nothing has inspected has no streams to name,
    which is the same `500` as an index that names none."""
    try:
        return inspection_of(request, found)
    except DeliveryProductionError as error:
        raise SubtitleUnavailableError from error


def _stream_named(inspection: MediaInspection, index: int) -> InspectedStream:
    """The subtitle stream this **wire** index names, or the measured `500`.

    One lookup for four rows of the error table - an index naming no stream, one naming a video
    stream, one naming an audio stream and a negative one - because the reference takes the first
    match of a sequence and throws the same way for all four.
    """
    for stream in inspection.streams:
        if stream.index == index and stream.kind is StreamKind.SUBTITLE:
            return stream
    raise SubtitleUnavailableError


async def _readable(
    request: Request,
    found: DeliveredFile,
    inspection: MediaInspection,
    stream: InspectedStream,
) -> tuple[bytes, str]:
    """The bytes of the readable file and the format they are in.

    Bytes rather than text because of the short circuit above: an artefact is handed back exactly
    as it lies, byte order mark included, and decoding it here would consume the mark.
    """
    try:
        return await extract.verbatim(
            production_ledger(request),
            get_paths(request).cache / extract.DIRECTORY,
            found,
            inspection,
            stream,
        )
    except extract.ImageSubtitleError as error:
        # The reference attempts the extraction and refuses about twenty seconds later; this is
        # the same status and the same bytes without starting a process (plan section 6.7).
        raise SubtitleRequestError from error
    except ffmpeg.ProductionError as error:
        raise SubtitleUnavailableError from error


def _answer(body: bytes, media_type: str) -> Response:
    """The measured header set: a `Content-Type` with no charset, a `Content-Length`, nothing else.

    The type is set as a **header** rather than through `media_type`, for the reason
    `compat/errors.py` gives: Starlette appends `; charset=utf-8` to any `text/*` type it is
    given, and the reference sends a bare `text/vtt`.
    """
    return Response(content=body, status_code=200, headers={"Content-Type": media_type})


__all__ = ["PLAYLIST", "WITHOUT_TICKS", "WITH_TICKS", "router"]
