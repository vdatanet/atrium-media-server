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

import hashlib
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from email.utils import format_datetime
from pathlib import Path
from typing import Annotated

from fastapi import Query, Request
from starlette.responses import Response, StreamingResponse

from atrium.api.deps import get_paths, get_sessions
from atrium.compat.errors import (
    DeliveryNotFoundError,
    DeliveryProductionError,
    DeliverySourceError,
)
from atrium.compat.guids import new_id
from atrium.compat.ranges import RangeAnswer, negotiate_range
from atrium.db.engine import session_scope
from atrium.db.repositories import MediaFileRepository, MediaProbeRepository
from atrium.domain.media import DeliveredFile, InspectedStream, MediaInspection, StreamKind
from atrium.media import ffmpeg
from atrium.media.decision import (
    CodecKind,
    CodecProfile,
    ConditionProperty,
    ConditionType,
    Decision,
    DeviceProfile,
    MediaKind,
    Outcome,
    ProfileCondition,
    Switches,
    TranscodingProfile,
    decide,
)
from atrium.media.info import source_id
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


#: What the produced half answers instead of `Accept-Ranges: bytes` when it cannot say how long
#: the body will be. Measured on a remux, a re-encode and a produced `stream.mp3`, all three
#: `[probe: tools/probe_progressive_delivery.py, Jellyfin 10.11.11, 2026-08-29]`.
NO_RANGES = "none"

#: The destination a command is built with when only its *shape* is wanted - the scratch file is
#: named after the command, so the command cannot already know the name. Anything that is not
#: `PIPE` will do, because all the placeholder decides is that the output is seekable.
UNNAMED_DESTINATION = "output"

#: The output extension a produced request falls back to when neither the path, the `container`
#: parameter nor a requested codec names one - inferred from the codec the client asked for, and
#: then from the source's own stored container. Both tables are the reference's own inference and
#: were measured through their observable, the `Content-Type` of a bare non-static request
#: `[source: Jellyfin.Api/Helpers/StreamingHelpers.cs GetOutputFileExtension @ v10.11.11]`,
#: `[probe: tools/probe_progressive_delivery.py, Jellyfin 10.11.11, 2026-08-29]`.
VIDEO_OUTPUT_CONTAINERS: dict[str, str] = {
    "h264": "ts",
    "hevc": "mp4",
    "av1": "mp4",
    "theora": "ogv",
    "vp8": "webm",
    "vp9": "webm",
    "vpx": "webm",
    "wmv": "asf",
}
AUDIO_OUTPUT_CONTAINERS: dict[str, str] = {
    "aac": "aac",
    "mp3": "mp3",
    "vorbis": "ogg",
    "wma": "wma",
}


@dataclass(frozen=True, slots=True)
class DeliveryParameters:
    """What a produced request says it wants, as both controllers bind it.

    Every field is one the negotiated `TranscodingUrl` renders (`media/urls.py`), which is what
    makes the pair a round trip: T5 writes these names and this reads them back. A parameter the
    reference declares and this does not is a gap rather than a difference - an unrecognised query
    value is ignored on both servers (behaviours section 1.12) - and the ones still owed belong to
    the tasks that honour them.
    """

    container: str | None = None
    media_source_id: str | None = None
    video_codec: str | None = None
    audio_codec: str | None = None
    audio_stream_index: int | None = None
    video_bit_rate: int | None = None
    audio_bit_rate: int | None = None
    audio_sample_rate: int | None = None
    max_audio_channels: int | None = None
    max_width: int | None = None
    max_height: int | None = None
    max_framerate: float | None = None
    max_video_bit_depth: int | None = None
    start_time_ticks: int | None = None
    allow_video_stream_copy: bool = True
    allow_audio_stream_copy: bool = True


def video_parameters(
    mediaSourceId: Annotated[str | None, Query()] = None,  # noqa: N803 - the wire's spellings
    videoCodec: Annotated[str | None, Query(pattern=CONTAINER_PATTERN)] = None,  # noqa: N803
    audioCodec: Annotated[str | None, Query(pattern=CONTAINER_PATTERN)] = None,  # noqa: N803
    audioStreamIndex: Annotated[int | None, Query()] = None,  # noqa: N803
    videoBitRate: Annotated[int | None, Query()] = None,  # noqa: N803
    audioBitRate: Annotated[int | None, Query()] = None,  # noqa: N803
    audioSampleRate: Annotated[int | None, Query()] = None,  # noqa: N803
    maxAudioChannels: Annotated[int | None, Query()] = None,  # noqa: N803
    maxWidth: Annotated[int | None, Query()] = None,  # noqa: N803
    maxHeight: Annotated[int | None, Query()] = None,  # noqa: N803
    maxFramerate: Annotated[float | None, Query()] = None,  # noqa: N803
    maxVideoBitDepth: Annotated[int | None, Query()] = None,  # noqa: N803
    startTimeTicks: Annotated[int | None, Query()] = None,  # noqa: N803
    allowVideoStreamCopy: Annotated[bool | None, Query()] = None,  # noqa: N803
    allowAudioStreamCopy: Annotated[bool | None, Query()] = None,  # noqa: N803
) -> DeliveryParameters:
    """The query set the two `/Videos` routes declare, bound once.

    A dependency rather than a signature repeated four times, which is safe here because
    `compat/query_params.py` walks sub-dependencies when it builds the case-insensitive spelling
    table - a parameter declared by a shared dependency is as bindable as one in the handler's
    own signature, and it says so.

    **`container` is deliberately not here.** It is a path parameter on one route of each pair and
    a query parameter on the other, and a dependency declaring it would collide with the path's
    own on the suffixed form. Each route binds its own and hands it to `with_container`.
    """
    return DeliveryParameters(
        media_source_id=mediaSourceId,
        video_codec=videoCodec,
        audio_codec=audioCodec,
        audio_stream_index=audioStreamIndex,
        video_bit_rate=videoBitRate,
        audio_bit_rate=audioBitRate,
        audio_sample_rate=audioSampleRate,
        max_audio_channels=maxAudioChannels,
        max_width=maxWidth,
        max_height=maxHeight,
        max_framerate=maxFramerate,
        max_video_bit_depth=maxVideoBitDepth,
        start_time_ticks=startTimeTicks,
        # Both default to true when absent, which is the reference's own default and what makes a
        # bare request a remux rather than a re-encode of everything it was handed.
        allow_video_stream_copy=allowVideoStreamCopy is not False,
        allow_audio_stream_copy=allowAudioStreamCopy is not False,
    )


def audio_parameters(
    mediaSourceId: Annotated[str | None, Query()] = None,  # noqa: N803
    videoCodec: Annotated[str | None, Query(pattern=CONTAINER_PATTERN)] = None,  # noqa: N803
    audioCodec: Annotated[str | None, Query(pattern=CONTAINER_PATTERN)] = None,  # noqa: N803
    audioStreamIndex: Annotated[int | None, Query()] = None,  # noqa: N803
    videoBitRate: Annotated[int | None, Query()] = None,  # noqa: N803
    audioBitRate: Annotated[int | None, Query()] = None,  # noqa: N803
    audioSampleRate: Annotated[int | None, Query()] = None,  # noqa: N803
    maxAudioChannels: Annotated[int | None, Query()] = None,  # noqa: N803
    maxFramerate: Annotated[float | None, Query()] = None,  # noqa: N803
    maxVideoBitDepth: Annotated[int | None, Query()] = None,  # noqa: N803
    startTimeTicks: Annotated[int | None, Query()] = None,  # noqa: N803
    allowVideoStreamCopy: Annotated[bool | None, Query()] = None,  # noqa: N803
    allowAudioStreamCopy: Annotated[bool | None, Query()] = None,  # noqa: N803
) -> DeliveryParameters:
    """The audio pair's set, which is the video one **without `maxWidth` and `maxHeight`**.

    That absence is the reference's, not a simplification: its audio action declares `width` and
    `height` and no maxima, where the video one declares both pairs `[source:
    Jellyfin.Api/Controllers/VideosController.cs:347-348,
    Jellyfin.Api/Controllers/AudioController.cs:93-145 @ v10.11.11]`. A client sending `maxWidth`
    to `/Audio/{id}/stream` is sending a parameter neither server declares, and behaviours section
    1.12 says what happens to those: nothing.
    """
    return video_parameters(
        mediaSourceId=mediaSourceId,
        videoCodec=videoCodec,
        audioCodec=audioCodec,
        audioStreamIndex=audioStreamIndex,
        videoBitRate=videoBitRate,
        audioBitRate=audioBitRate,
        audioSampleRate=audioSampleRate,
        maxAudioChannels=maxAudioChannels,
        maxFramerate=maxFramerate,
        maxVideoBitDepth=maxVideoBitDepth,
        startTimeTicks=startTimeTicks,
        allowVideoStreamCopy=allowVideoStreamCopy,
        allowAudioStreamCopy=allowAudioStreamCopy,
    )


def with_container(parameters: DeliveryParameters, container: str | None) -> DeliveryParameters:
    """The bound set plus the container this route named, wherever it named it."""
    return replace(parameters, container=container)


def static_response(
    request: Request, item_id: str, container: str | None, media_source_id: str | None = None
) -> Response:
    """One `static=true` answer, for either route family.

    The container is the path's suffix, or `None` on the unsuffixed form - and in both cases the
    bytes are the file's. `container` also arrives as a query parameter on the unsuffixed route
    and means the same thing there, measured.
    """
    found, absolute = _locate(request, item_id, media_source_id)
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


def _locate(
    request: Request, item_id: str, media_source_id: str | None
) -> tuple[DeliveredFile, str]:
    """The part this request is about, and where its bytes are.

    **`mediaSourceId` is resolved here for both halves of every route**, because the reference
    resolves it in one helper both halves go through: the answers to a well-formed identifier
    naming no source and to one that is not an identifier at all are identical on a `static=true`
    request and on a produced one `[probe: tools/probe_progressive_delivery.py, Jellyfin 10.11.11,
    2026-08-29]`. Absent, it is part zero, which is what the reference serves when the parameter
    is not given.
    """
    with session_scope(get_sessions(request)) as opened:
        repository = MediaFileRepository(opened)
        part_index = 0
        if media_source_id:
            part_index = _part_named(repository.parts(item_id), item_id, media_source_id)
        found = repository.locate(item_id, part_index)
    absolute = None if found is None else found.absolute_path()
    if found is None or absolute is None:
        raise DeliveryNotFoundError
    return found, absolute


def _part_named(paths: tuple[str, ...], item_id: str, media_source_id: str) -> int:
    """Which part the identifier names, or the measured refusal when it names none.

    The reference splits this refusal in two by an accident of order: it compares the identifier
    against each source, and then - only when none matched - *parses* it to see whether it is the
    item's own. A well-formed identifier that matches nothing answers `400`; one that is not an
    identifier at all throws out of `Guid.Parse` and answers `500`, since a `FormatException` is
    not a type its middleware maps `[source: Jellyfin.Api/Helpers/StreamingHelpers.cs:136-140 @
    v10.11.11]`, `[probe: tools/probe_progressive_delivery.py, Jellyfin 10.11.11, 2026-08-29]`.

    **Atrium answers the `400` for both**, which is behaviours section 3.9's divergence: both
    values mean "this names no source of this item", the `400` is the answer the reference itself
    gives that sentence one value away, and reproducing the split would mean writing a parse whose
    only purpose is to fail worse.
    """
    wanted = media_source_id.strip().lower()
    for index, relative_path in enumerate(paths):
        if source_id(item_id, index, relative_path).lower() == wanted:
            return index
    raise DeliverySourceError


def _ranged(
    path: str, answer: RangeAnswer, *, media_type: str, last_modified: datetime | None = None
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
    if last_modified is not None:
        # **Absent on a produced answer**, and that absence is the shape of the divergence rather
        # than an oversight. The reference sends no header at all on a progressive response; what
        # Atrium adds is a size and a range unit, because a renderer will not touch a stream whose
        # length it does not know (behaviours section 3.3). A modification time for bytes that did
        # not exist a second ago would be a second, unargued difference.
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


# ------------------------------------------------------------------------------------------------
# The produced half: a remux is sized, a re-encode is chunked
# ------------------------------------------------------------------------------------------------


async def produced_response(
    request: Request, item_id: str, parameters: DeliveryParameters, *, is_video_route: bool
) -> Response:
    """A non-static delivery: the file remuxed or re-encoded to what the client asked for.

    Two answers, decided by the one property of the decision that matters here - whether any
    stream is made again:

    * every stream copied is a **remux**, produced to scratch and then served whole, so it carries
      a `Content-Length` and honours `Range` (AC-15, the divergence of behaviours section 3.3);
    * anything re-encoded is **chunked** with `Accept-Ranges: none` and no length, because the
      final length is not known until the last frame (AC-17), which is exactly the reference's
      progressive shape.

    `is_video_route` is the controller, and it decides only the fallback container. Whether the
    *negotiation* is about video is the item's kind, which is what `decide()` was given at T4.
    """
    found, absolute = _locate(request, item_id, parameters.media_source_id)
    inspection = _inspection(request, found)
    decision, container = _decide_delivery(
        inspection, parameters, is_video_route=is_video_route, is_video=found.is_video
    )
    if decision.outcome is Outcome.NONE:
        # Nothing can be produced for what was asked - the measured `500`, the same one an
        # unmuxable container gets, because on the reference both are an encoder that never
        # started (behaviours section 1.11's third shape).
        raise DeliveryProductionError
    media_type = label_for(container, found.relative_path)
    ledger = production_ledger(request)

    try:
        if decision.outcome is Outcome.REMUX:
            produced = await _remuxed(
                ledger,
                get_paths(request).transcodes,
                inspection,
                decision,
                container,
                path=absolute,
                start_ticks=parameters.start_time_ticks,
            )
            answer = negotiate_range(request.headers.get("range"), produced.stat().st_size)
            return _ranged(str(produced), answer, media_type=media_type)

        return await _chunked(
            ledger,
            inspection,
            decision,
            container,
            path=absolute,
            start_ticks=parameters.start_time_ticks,
            media_type=media_type,
        )
    except ffmpeg.ProductionError as error:
        # A command that could not be built at all - no muxer for the container, no encoder for
        # the codec, no ffmpeg on PATH - is the same answer as one that started and died, because
        # that is what the reference answers to all of them.
        raise DeliveryProductionError from error


def production_ledger(request: Request) -> ffmpeg.ProductionLedger:
    """One per application, reached the way `api/images.py` reaches its cache.

    On the application rather than in a module global so two applications in one process - which
    is every conformance test in this repository - cannot see each other's processes, and so that
    008 T11's manager has somewhere to hang beside it.
    """
    existing: ffmpeg.ProductionLedger | None = getattr(request.app.state, "productions", None)
    if existing is None:
        existing = ffmpeg.ProductionLedger()
        request.app.state.productions = existing
    return existing


def _inspection(request: Request, found: DeliveredFile) -> MediaInspection:
    """What was stored about this file, or the refusal that says nothing can be produced.

    A file nothing has inspected cannot be negotiated about: there are no streams to copy, no
    codecs to compare and no indexes to map. The static half needs none of this, which is why it
    keeps working for an item a scan has not reached.
    """
    if found.library_id is None:
        raise DeliveryProductionError
    with session_scope(get_sessions(request)) as opened:
        stored = MediaProbeRepository(opened).get(found.library_id, found.relative_path)
    if stored is None:
        raise DeliveryProductionError
    return stored


def _decide_delivery(
    source: MediaInspection,
    parameters: DeliveryParameters,
    *,
    is_video_route: bool,
    is_video: bool,
) -> tuple[Decision, str]:
    """The delivery request, run through the one ladder, plus the container it produces into.

    **A `stream` request is a device profile with the client's words in it.** The parameters
    describe an output - these codecs, inside these ceilings - and `media/decision.py` already
    turns exactly that into stream plans, so this synthesises the profile rather than writing a
    second copy-or-encode rule beside the one T4 proved (plan section 6.6 does the same for
    `/universal`). The synthesised profile lists **no direct-play entry**, which is right: a
    `static=true` request is the direct play on these routes, and everything else is a production.

    A codec the client did not name is the source's own, which is how a bare request remuxes
    rather than refusing - measured, and it is what the reference's own fallback chain produces.
    """
    video = source.video if is_video else None
    audio = _audio_stream(source, parameters.audio_stream_index)
    video_codec = parameters.video_codec or (video.codec if video is not None else None)
    audio_codec = parameters.audio_codec or (audio.codec if audio is not None else None)
    container = _output_container(
        source,
        parameters.container,
        video_codec=parameters.video_codec,
        audio_codec=parameters.audio_codec,
        is_video_route=is_video_route,
    )
    profile = DeviceProfile(
        transcoding_profiles=(
            TranscodingProfile(
                container=container,
                video_codec=video_codec,
                audio_codec=audio_codec,
                type=MediaKind.VIDEO if is_video else MediaKind.AUDIO,
                protocol="http",
            ),
        ),
        codec_profiles=tuple(_ceiling_profiles(parameters, is_video=is_video)),
    )
    switches = Switches(
        allow_video_stream_copy=parameters.allow_video_stream_copy,
        allow_audio_stream_copy=parameters.allow_audio_stream_copy,
        audio_stream_index=parameters.audio_stream_index,
        max_audio_channels=parameters.max_audio_channels,
    )
    # No policy gate here: these routes take no user at all (behaviours section 2.10), so there is
    # no account whose permissions could be read. The delivery half of AC-31 belongs to T13, which
    # is the task that decides what a session does with the policy it was negotiated under.
    return decide(source, profile, switches, is_video=is_video), container


def _audio_stream(source: MediaInspection, index: int | None) -> InspectedStream | None:
    audio = [one for one in source.streams if one.kind is StreamKind.AUDIO]
    if not audio:
        return None
    if index is not None:
        named = next((one for one in audio if one.index == index), None)
        if named is not None:
            return named
    return audio[0]


def _ceiling_profiles(parameters: DeliveryParameters, *, is_video: bool) -> Iterator[CodecProfile]:
    """The client's ceilings, expressed as the conditions the ladder already reads.

    `LessThanEqual` on every one of them, because that is what a `Max*` parameter means and it is
    the only comparison `decision.ceiling` treats as an upper bound.
    """
    video_limits = _conditions(
        (ConditionProperty.WIDTH, parameters.max_width),
        (ConditionProperty.HEIGHT, parameters.max_height),
        (ConditionProperty.VIDEO_BITRATE, parameters.video_bit_rate),
        (ConditionProperty.VIDEO_FRAMERATE, parameters.max_framerate),
        (ConditionProperty.VIDEO_BIT_DEPTH, parameters.max_video_bit_depth),
    )
    if video_limits:
        yield CodecProfile(type=CodecKind.VIDEO, conditions=video_limits)
    audio_limits = _conditions(
        (ConditionProperty.AUDIO_CHANNELS, parameters.max_audio_channels),
        (ConditionProperty.AUDIO_BITRATE, parameters.audio_bit_rate),
        (ConditionProperty.AUDIO_SAMPLE_RATE, parameters.audio_sample_rate),
    )
    if audio_limits:
        yield CodecProfile(
            type=CodecKind.VIDEO_AUDIO if is_video else CodecKind.AUDIO,
            conditions=audio_limits,
        )


def _conditions(
    *stated: tuple[ConditionProperty, float | None],
) -> tuple[ProfileCondition, ...]:
    return tuple(
        ProfileCondition(
            condition=ConditionType.LESS_THAN_EQUAL,
            property=wanted,
            value=_number(value),
        )
        for wanted, value in stated
        if value is not None
    )


def _number(value: float) -> str:
    """A ceiling as the string a `ProfileCondition` carries, integral where it is whole."""
    return str(int(value)) if float(value).is_integer() else str(value)


def _output_container(
    source: MediaInspection,
    requested: str | None,
    *,
    video_codec: str | None,
    audio_codec: str | None,
    is_video_route: bool,
) -> str:
    """What the produced bytes are muxed into, in the reference's measured order.

    The path suffix or the `container` parameter first; then the codec the client asked for,
    through the table it infers one from; and finally the **first member of the source's stored
    container string**, which is a third derivation of "the container" beside the two 008 T2
    found - a bare `/Audio/{id}/stream` on an `.m4a` answers `video/quicktime`, because the stored
    `mov,mp4,m4a,3gp,3g2,mj2` begins with `mov` `[probe: tools/probe_progressive_delivery.py,
    Jellyfin 10.11.11, 2026-08-29]`.
    """
    if requested:
        return requested.strip().lstrip(".").lower()
    table = VIDEO_OUTPUT_CONTAINERS if is_video_route else AUDIO_OUTPUT_CONTAINERS
    asked = (video_codec if is_video_route else audio_codec) or ""
    named = table.get(asked.strip().lower())
    if named is not None:
        return named
    stored = (source.container or "").split(",")[0].strip()
    return stored.lower()


async def _remuxed(
    ledger: ffmpeg.ProductionLedger,
    scratch: Path,
    source: MediaInspection,
    decision: Decision,
    container: str,
    *,
    path: str,
    start_ticks: int | None,
) -> Path:
    """Produce a copy-only output to a file, and hand back where it landed.

    **Deterministic by name.** Spec section 3.4 makes the byte-identity of a remux global rather
    than per session - the same source and the same parameters give the same output - so the
    scratch file is named after the command and the file's change signal, and a second request for
    the same thing serves what the first produced. That is what makes `Range` on this answer cheap
    rather than a re-encode per seek.

    Published with a rename, the same rule the media fixtures follow: two requests racing either
    both see a complete file or one of them throws its own away, and a half-written remux is never
    visible under the name anything serves.
    """
    template = ffmpeg.command(
        source,
        decision,
        ffmpeg.Output(container=container, destination=UNNAMED_DESTINATION),
        path=path,
        start_ticks=start_ticks,
    )
    scratch.mkdir(parents=True, exist_ok=True)
    settled = scratch / f"{_digest(template[:-1], path)}.{container}"
    if settled.exists():
        return settled

    partial = settled.with_name(f"{settled.name}.{new_id()}.partial")
    running = await ledger.start([*template[:-1], str(partial)], to_pipe=False)
    try:
        code = await running.process.wait()
    finally:
        await ledger.finish(running)
    if code != 0 or not partial.exists():
        partial.unlink(missing_ok=True)
        raise DeliveryProductionError
    partial.replace(settled)
    return settled


def _digest(argv: list[str], path: str) -> str:
    """A name for one produced output: this command, over this file, in this state.

    The change signal goes in beside the command, so a file replaced on disk is a different name
    rather than a stale hit - the failure 003's `(size, mtime_ns)` pair exists to catch, met here
    for the second time.
    """
    stat = Path(path).stat()
    material = "\0".join([*argv, str(stat.st_size), str(stat.st_mtime_ns)])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


async def _chunked(
    ledger: ffmpeg.ProductionLedger,
    source: MediaInspection,
    decision: Decision,
    container: str,
    *,
    path: str,
    start_ticks: int | None,
    media_type: str,
) -> Response:
    """A re-encode, streamed as it is produced: no length, no ranges, and no invented number.

    The first block is read **before** the response is returned, which is what lets an encoder
    that dies on the way up answer the measured `500` instead of a `200` with an empty body -
    the failure `/universal` has and behaviours section 3.8 refuses to reproduce, met here on
    a route where the reference itself refuses.
    """
    argv = ffmpeg.command(
        source,
        decision,
        ffmpeg.Output(container=container, destination=ffmpeg.PIPE),
        path=path,
        start_ticks=start_ticks,
    )
    running = await ledger.start(argv, to_pipe=True)
    stream = running.process.stdout
    first = b"" if stream is None else await stream.read(ffmpeg.CHUNK_BYTES)
    if not first:
        await ledger.finish(running)
        raise DeliveryProductionError
    return StreamingResponse(
        _produced_bytes(ledger, running, first),
        status_code=200,
        headers={"Content-Type": media_type, "Accept-Ranges": NO_RANGES},
    )


async def _produced_bytes(
    ledger: ffmpeg.ProductionLedger, running: ffmpeg.Production, first: bytes
) -> AsyncIterator[bytes]:
    """The body, and the cancellation path AC-26 is about.

    A client that disconnects makes the framework close this generator, and the `finally` is where
    the encoder stops - which is a claim a test can check, because the ledger is what empties.
    """
    stream = running.process.stdout
    try:
        yield first
        while stream is not None and (block := await stream.read(ffmpeg.CHUNK_BYTES)):
            yield block
    finally:
        await ledger.finish(running)


__all__ = [
    "ACCEPT_RANGES",
    "AUDIO_OUTPUT_CONTAINERS",
    "CHUNK_BYTES",
    "CONTAINER_PATTERN",
    "NO_RANGES",
    "UNNAMED_DESTINATION",
    "VIDEO_OUTPUT_CONTAINERS",
    "DeliveryParameters",
    "audio_parameters",
    "produced_response",
    "production_ledger",
    "static_response",
    "video_parameters",
    "with_container",
]
