# SPDX-License-Identifier: GPL-3.0-or-later
"""The subtitle playlist route, over HTTP, against a track whose runtime the wire states.

011 T8. `GET …/Subtitles/{index}/subtitles.m3u8` is the address a manifest entry names, and what
is asserted here is what a client receives: the playlist's own header order, one window per
`segmentLength` seconds of the runtime, the invariant decimal point of AC-16, every row of
[spec section 3.7]'s **playlist** column - which is not its fetch column on a single condition
that fails - and AC-8's traversal, which follows every entry as written.

**The expected playlist is built here from the runtime the wire states**, not by calling the
renderer the route calls. 008 T16's lesson: a golden produced by the code under test compares
Atrium against itself. The runtime comes off `/Items/{itemId}` because that is where a client
reads it, and the arithmetic below is integer division rather than the renderer's `Decimal`.

**The runtime is read and not written down.** The generated film is declared at 4 s and the
container states 4.021 s on one extraction build; a literal here would be true of one of them
(011 T6). Every expectation is derived from what the source says.

`[probe: tools/probe_subtitle_delivery.py, Jellyfin 10.11.11, 2026-08-30]` is the measurement
behind every status, header and line below.
"""

from __future__ import annotations

import json
import locale
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI, Request

from atrium.api.deps import require_user
from atrium.compat.errors import CONTROLLER_ERROR_BODY, CONTROLLER_ERROR_TYPE
from atrium.config.paths import DataPaths
from atrium.db.repositories import UserRepository
from atrium.domain.items import ItemType
from atrium.domain.user import User
from atrium.media.labels import media_type_of
from atrium.server import create_app
from tests.conformance.test_golden import STATE
from tests.fixtures.media import (
    BOTH_SUBTITLE_KINDS,
    BuiltMedia,
    ScannedMediaWorld,
    build_scanned_media_world,
)

pytestmark = [pytest.mark.conformance, pytest.mark.ffmpeg]

VIEWER_ID = "e" * 32

#: An identifier no scan produced, and the all-zero form beside it - two rows of section 3.7 that
#: answer differently on this route: problem details for the first, the controller's `400` for the
#: second.
UNKNOWN_ITEM = "deadbeefdeadbeefdeadbeefdeadbeef"
EMPTY_GUID = "0" * 32

TICKS_PER_SECOND = 10_000_000

#: What the route is labelled with, measured - the same row 008's two playlists read.
PLAYLIST_TYPE = media_type_of("m3u8")

#: The whole header set a playlist answers, measured: a `Content-Type`, a `Content-Length`, and
#: **no `Accept-Ranges`** - the header 008 T14 found false of the two HLS playlists and false
#: again here.
PLAYLIST_HEADERS = {"content-length", "content-type"}

#: What 001's middleware puts on every response, excluded above.
ALWAYS = {"server", "x-response-time-ms"}

#: Locales whose decimal separator is a comma. The first one this host can set is used, and a host
#: that can set none still runs every assertion (Principle VII forbids depending on the host's
#: locale; this only makes the test harder where one exists).
COMMA_LOCALES = ("es_ES.UTF-8", "es_ES.utf8", "de_DE.UTF-8", "fr_FR.UTF-8", "pt_BR.UTF-8")


# ------------------------------------------------------------------------------------------
# The world, served
# ------------------------------------------------------------------------------------------


@pytest.fixture
def media_paths(tmp_path: Path) -> DataPaths:
    paths = DataPaths(tmp_path / "atrium")
    paths.prepare()
    paths.state_file.write_text(json.dumps(STATE, indent=1), encoding="utf-8")
    return paths


@pytest.fixture
def served(
    media_paths: DataPaths, media_files: BuiltMedia
) -> Iterator[tuple[FastAPI, ScannedMediaWorld]]:
    built = create_app(media_paths)
    built.state.readiness.mark_ready()
    with built.state.sessions.begin() as opened:
        world = build_scanned_media_world(opened, media_files)
        UserRepository(opened).add(User(id=VIEWER_ID, name="viewer", enable_all_folders=True))
    built.dependency_overrides[require_user] = _as_viewer
    yield built, world
    built.dependency_overrides.clear()
    built.state.db.dispose()


def _as_viewer(request: Request) -> User:
    request.state.session_id = None
    request.state.token_sha256 = None
    return User(id=VIEWER_ID, name="viewer", enable_all_folders=True)


@pytest.fixture
async def client(served: tuple[FastAPI, ScannedMediaWorld]) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=served[0])
    async with httpx.AsyncClient(transport=transport, base_url="http://atrium:8096") as opened:
        yield opened


@pytest.fixture
async def unauthenticated(
    served: tuple[FastAPI, ScannedMediaWorld],
) -> AsyncIterator[httpx.AsyncClient]:
    """The same application with **no dependency override**, so `require_user` is the real one.

    This route is the one of the three that wants a caller, so without this the credential test
    would be asserting an override rather than the route.
    """
    served[0].dependency_overrides.clear()
    transport = httpx.ASGITransport(app=served[0])
    async with httpx.AsyncClient(transport=transport, base_url="http://atrium:8096") as opened:
        yield opened


# ------------------------------------------------------------------------------------------
# Naming a track, and what the source says about itself
# ------------------------------------------------------------------------------------------


async def source_of(client: httpx.AsyncClient, item_id: str) -> dict[str, Any]:
    """The item's first media source as a client reads it - where the runtime and the wire
    indexes both are."""
    answered = await client.get(f"/Items/{item_id}")
    assert answered.status_code == 200
    sources: list[dict[str, Any]] = answered.json()["MediaSources"]
    return sources[0]


async def subtitled(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> tuple[str, int, int]:
    """The item id, the wire index of its text subtitle track, and the source's runtime."""
    item_id = served[1].of(BOTH_SUBTITLE_KINDS).id
    source = await source_of(client, item_id)
    index = next(
        int(one["Index"])
        for one in source["MediaStreams"]
        if one["Type"] == "Subtitle" and str(one.get("Codec", "")).lower() == "subrip"
    )
    runtime = int(source["RunTimeTicks"])
    assert runtime > 0, "the fixture states no runtime, so nothing below is about the route"
    return item_id, index, runtime


def address(item_id: str, index: int, *, source_id: str | None = None) -> str:
    """One track's playlist address. Part zero's source id is the item's own (`media/info.py`)."""
    return f"/Videos/{item_id}/{source_id or item_id}/Subtitles/{index}/subtitles.m3u8"


def duration_text(ticks: int) -> str:
    """The `#EXTINF` number, derived here by integer arithmetic rather than by the renderer's.

    A second derivation on purpose: the assertion is about the bytes a client reads, and a helper
    that called the module under test would agree with it however wrong both were.
    """
    whole, rest = divmod(ticks, TICKS_PER_SECOND)
    return str(whole) if rest == 0 else f"{whole}.{rest:07d}".rstrip("0")


def expected_playlist(runtime_ticks: int, seconds: int, token: str) -> str:
    """The whole document, written out from the runtime the wire stated."""
    window = seconds * TICKS_PER_SECOND
    lines = [
        "#EXTM3U",
        f"#EXT-X-TARGETDURATION:{seconds}",
        "#EXT-X-VERSION:3",
        "#EXT-X-MEDIA-SEQUENCE:0",
        "#EXT-X-PLAYLIST-TYPE:VOD",
    ]
    for start in range(0, runtime_ticks, window):
        end = min(runtime_ticks, start + window)
        lines.append(f"#EXTINF:{duration_text(end - start)},")
        lines.append(
            "stream.vtt?CopyTimestamps=true&AddVttTimeMap=true"
            f"&StartPositionTicks={start}&EndPositionTicks={end}&ApiKey={token}"
        )
    lines.append("#EXT-X-ENDLIST")
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------------------------------
# The playlist itself
# ------------------------------------------------------------------------------------------


async def test_the_playlist_is_the_measured_shape_and_covers_the_runtime(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """The whole document, byte for byte, against the runtime the source states.

    The header order is this route's own and not the media playlist's, `#EXT-X-TARGETDURATION` is
    the *requested* window rather than the longest entry, and the entries name a lower-case
    `stream.vtt` with both timestamp switches set and the caller's token appended.
    """
    item_id, index, runtime = await subtitled(client, served)

    answered = await client.get(address(item_id, index), params={"SegmentLength": 1, "ApiKey": "t"})

    assert answered.status_code == 200
    assert answered.headers["Content-Type"] == PLAYLIST_TYPE
    assert answered.headers["Content-Length"] == str(len(answered.content))
    assert set(answered.headers) - ALWAYS == PLAYLIST_HEADERS
    assert answered.text == expected_playlist(runtime, 1, "t")


async def test_the_last_window_is_clamped_to_the_runtime(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """Window coverage: one entry per window, the grid advancing by the requested length, and the
    last window's end position the runtime itself rather than the grid's next multiple."""
    item_id, index, runtime = await subtitled(client, served)

    answered = await client.get(address(item_id, index), params={"SegmentLength": 3})

    entries = [line for line in answered.text.splitlines() if not line.startswith("#")]
    assert len(entries) == -(-runtime // (3 * TICKS_PER_SECOND))
    assert entries[0].endswith("&StartPositionTicks=0&EndPositionTicks=30000000&ApiKey=")
    assert entries[-1].endswith(f"&EndPositionTicks={runtime}&ApiKey=")


async def test_ac16_a_partial_window_is_written_with_a_decimal_point(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """AC-16 and behaviours section 3.12, at the boundary a client reads.

    The reference writes this number in the **server's** culture, so a Spanish-configured host
    answers `#EXTINF:7,851,` inside a file whose grammar reads that as a duration of `7` and a
    title of `851`. Atrium writes the point always. The locale is set here because that is the
    only thing that could make this fail - and a host that has no comma locale still runs every
    assertion, since Principle VII forbids a test that depends on the host's.

    A whole window is still written `30` and not `30.0`, so the divergence is visible on the last
    window and nowhere else.

    **Whether this container's last window is fractional is a fact about the extraction build**,
    so the unconditional assertion is that every duration is exactly what the runtime says it is;
    the reference's own measured runtime, whose last window reads `7,851` there, is pinned
    unconditionally in `tests/unit/test_hls_planning.py`.
    """
    item_id, index, runtime = await subtitled(client, served)
    remainder = runtime % (3 * TICKS_PER_SECOND)

    previous = locale.setlocale(locale.LC_ALL)
    try:
        for candidate in COMMA_LOCALES:
            try:
                locale.setlocale(locale.LC_ALL, candidate)
            except locale.Error:
                continue
            break
        answered = await client.get(address(item_id, index), params={"SegmentLength": 3})
    finally:
        locale.setlocale(locale.LC_ALL, previous)

    expected = expected_playlist(runtime, 3, "")
    durations = [line for line in answered.text.splitlines() if line.startswith("#EXTINF")]
    assert answered.text == expected
    assert durations[0] == "#EXTINF:3,", "a whole window carries no decimal part"
    assert not any("," in line[len("#EXTINF:") : -1] for line in durations)
    if remainder % TICKS_PER_SECOND:
        assert durations[-1] == f"#EXTINF:{duration_text(remainder)}," and "." in durations[-1]


async def test_ac8_every_entry_is_fetched_by_following_it_as_written(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """AC-8's second half: the playlist is followed rather than read.

    Every entry names a lower-case `stream.vtt` where the fetch route is declared
    `Stream.{format}`, so this is also the assertion that 001's relaxed path matching serves the
    spelling the reference writes. A playlist that is well formed and leads nowhere passes a
    string comparison and fails this.
    """
    item_id, index, _runtime = await subtitled(client, served)
    answered = await client.get(address(item_id, index), params={"SegmentLength": 1})
    entries = [line for line in answered.text.splitlines() if not line.startswith("#")]

    assert entries, "nothing to follow"
    for entry in entries:
        followed = await client.get(f"/Videos/{item_id}/{item_id}/Subtitles/{index}/{entry}")

        assert followed.status_code == 200, entry
        assert followed.headers["Content-Type"] == "text/vtt"
        assert followed.text.startswith("WEBVTT\nX-TIMESTAMP-MAP="), (
            "the entries set AddVttTimeMap, which prepends the mapping line and drops the mark"
        )


# ------------------------------------------------------------------------------------------
# Spec section 3.7, the playlist column, row by row
# ------------------------------------------------------------------------------------------


async def test_a_caller_with_no_token_and_one_with_an_unknown_token_are_the_same_empty_401(
    unauthenticated: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """The row this route does not share with the two beside it: they serve the cues to anybody.

    Both refusals are the empty `401`, measured, and the token is accepted in the query string -
    which is how the addresses this feature emits work at all.
    """
    item_id = served[1].of(BOTH_SUBTITLE_KINDS).id

    for query in ({"SegmentLength": 30}, {"SegmentLength": 30, "ApiKey": "0" * 32}):
        answered = await unauthenticated.get(address(item_id, 0), params=query)

        assert answered.status_code == 401, query
        assert answered.content == b""


async def test_an_item_that_names_nothing_is_the_problem_details_404(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """The negotiation's shape, not the fetch routes' - the same identifier answers `400` in
    `text/plain` one route away, and this route resolves the item with the user."""
    answered = await client.get(address(UNKNOWN_ITEM, 0), params={"SegmentLength": 30})

    assert answered.status_code == 404
    assert answered.headers["Content-Type"] == "application/json; charset=utf-8"
    assert answered.json()["title"] == "Not Found"


async def test_an_item_that_exists_and_is_not_a_video_is_the_same_404(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """The cell section 3.7 left empty until T8, measured on a series identifier.

    The reference's own lookup asks for a video, so an item that is there and is not one is the
    `404` an identifier naming nothing gets - where the fetch routes answer `500` for exactly the
    same item. An audio track is this world's example of it. The dash is what let the first draft
    of this route reuse the fetch routes' lookup, and the table says `404` now.
    """
    audio = served[1].by_type(ItemType.AUDIO)
    assert audio, "the scanned world holds no audio item, so this row has nothing to run on"

    answered = await client.get(address(audio[0].id, 0), params={"SegmentLength": 30})

    assert answered.status_code == 404
    assert answered.json()["title"] == "Not Found"


async def test_the_all_zero_identifier_is_the_controller_refusal_at_400(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """A separate row from the one above, and a different answer: the reference guards the empty
    identifier before any lookup, so it never reaches the `404`."""
    answered = await client.get(address(EMPTY_GUID, 0), params={"SegmentLength": 30})

    assert answered.status_code == 400
    assert answered.headers["Content-Type"] == CONTROLLER_ERROR_TYPE
    assert answered.content == CONTROLLER_ERROR_BODY


async def test_an_identifier_that_is_not_one_names_this_routes_own_parameter(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """`itemId` and **not** `routeItemId`, measured at T8.

    Spec section 3.7 used to say both routes name `routeItemId`; only the fetch route had ever been
    asked, and the two declare that path segment under different names. A refusal that named the
    fetch routes' spelling would name a parameter this route does not have. The second assertion is
    not redundant with the first: it is what fails if the two ever collapse into one spelling.
    """
    answered = await client.get(
        "/Videos/not-a-guid/not-a-guid/Subtitles/0/subtitles.m3u8", params={"SegmentLength": 30}
    )

    assert answered.status_code == 400
    assert answered.headers["Content-Type"] == "application/json; charset=utf-8"
    assert "itemId" in answered.json()["errors"]
    assert "routeItemId" not in answered.json()["errors"]


async def test_a_media_source_that_names_nothing_is_the_500(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """The one refusal this route shares with the fetch routes, and the reference reaches it the
    same way: a source lookup that matches nothing, dereferenced one line later."""
    item_id, index, _runtime = await subtitled(client, served)

    answered = await client.get(
        address(item_id, index, source_id=UNKNOWN_ITEM), params={"SegmentLength": 30}
    )

    assert answered.status_code == 500
    assert answered.headers["Content-Type"] == CONTROLLER_ERROR_TYPE
    assert answered.content == CONTROLLER_ERROR_BODY
    assert "Accept-Ranges" not in answered.headers


async def test_an_index_naming_no_subtitle_is_still_a_whole_playlist(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """Three rows of section 3.7, one answer, and the sharpest reason AC-8 is a traversal.

    The route never reads the index it is given: no stream, a video stream and a negative index
    all answer the identical playlist - a hundred addresses each of which answers `500` when it is
    followed. Reproduced rather than improved, because a `404` here would refuse a request the
    reference serves.
    """
    item_id, index, _runtime = await subtitled(client, served)
    source = await source_of(client, item_id)
    video = next(int(one["Index"]) for one in source["MediaStreams"] if one["Type"] == "Video")

    served_playlist = await client.get(address(item_id, index), params={"SegmentLength": 30})
    for absent in (99, video, -1):
        answered = await client.get(address(item_id, absent), params={"SegmentLength": 30})

        assert answered.status_code == 200, absent
        assert answered.text == served_playlist.text

    # And what makes that a well-formed playlist leading nowhere: the addresses it names refuse.
    entry = served_playlist.text.splitlines()[6]
    followed = await client.get(f"/Videos/{item_id}/{item_id}/Subtitles/99/{entry}")
    assert followed.status_code == 500


@pytest.mark.parametrize("query", [{}, {"SegmentLength": "abc"}])
async def test_a_window_length_that_will_not_bind_is_problem_details_naming_it(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld], query: dict[str, str]
) -> None:
    """`segmentLength` is required, so an absent one is the framework's refusal and not a default.

    The reference declares it `[FromQuery, Required]`, and both an absent value and an unparseable
    one answer problem details naming it - the shape a refusal raised *before* the route runs
    always has.
    """
    item_id, index, _runtime = await subtitled(client, served)

    answered = await client.get(address(item_id, index), params=query)

    assert answered.status_code == 400
    assert answered.headers["Content-Type"] == "application/json; charset=utf-8"
    assert "segmentLength" in answered.json()["errors"]


async def test_a_window_length_of_zero_is_the_controller_refusal(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """Bound and then refused, which is the other shape: the value parses, the route rejects it.

    The pair above and this one are the clearest instance of section 3.7's split - the same
    parameter, two bodies, decided by whether the framework or the route said no.
    """
    item_id, index, _runtime = await subtitled(client, served)

    answered = await client.get(address(item_id, index), params={"SegmentLength": 0})

    assert answered.status_code == 400
    assert answered.headers["Content-Type"] == CONTROLLER_ERROR_TYPE
    assert answered.content == CONTROLLER_ERROR_BODY
