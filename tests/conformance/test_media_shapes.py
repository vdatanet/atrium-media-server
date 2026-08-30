# SPDX-License-Identifier: GPL-3.0-or-later
"""What a client receives about a real file, over a library that was really scanned.

`tests/golden/Items.*` already pin the media properties byte for byte, and they do it over the
seeded world of `tests/fixtures/query.py` - where the inspections are *stated*. That is the right
world for a golden and the wrong one for two claims:

* **AC-28** turns on a container string that is a demuxer *list*, and no path in the seeded world
  is an mp4. A fixture that claimed one was would be proving the rule against its own assumption.
* **One media source per part** is a statement about what 003 merged into one item, and only a
  real scan of two real files can say the merge happened.

So these run over 008 T1's generated matrix, scanned by the real pipeline and served through the
real routes - which makes them the only place where the file on disk, the row in the database and
the bytes on the wire are all the same claim.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from atrium.api.deps import require_user
from atrium.config.paths import DataPaths
from atrium.db.repositories import UserRepository
from atrium.domain.items import ItemType
from atrium.domain.user import User
from atrium.server import create_app
from tests.conformance.test_golden import STATE
from tests.fixtures.media import (
    BOTH_SUBTITLE_KINDS,
    DIRECT_PLAY,
    REJECTED_CONTAINER,
    TWO_PARTER_FIRST,
    TWO_PARTER_SECOND,
    BuiltMedia,
    ScannedMediaWorld,
    build_scanned_media_world,
)

pytestmark = [pytest.mark.conformance, pytest.mark.ffmpeg]

VIEWER_ID = "e" * 32


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
    """The real app over the real scan, committed so the routes' own sessions can see it."""
    built = create_app(media_paths)
    built.state.readiness.mark_ready()
    with built.state.sessions.begin() as opened:
        world = build_scanned_media_world(opened, media_files)
        viewer = UserRepository(opened).add(
            User(id=VIEWER_ID, name="viewer", enable_all_folders=True)
        )
    built.dependency_overrides[require_user] = lambda: viewer
    yield built, world
    built.dependency_overrides.clear()
    built.state.db.dispose()


@pytest.fixture
async def client(served: tuple[FastAPI, ScannedMediaWorld]) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=served[0])
    async with httpx.AsyncClient(transport=transport, base_url="http://atrium:8096") as opened:
        yield opened


async def body_of(client: httpx.AsyncClient, item_id: str) -> dict[str, Any]:
    answered = await client.get(f"/Items/{item_id}")
    assert answered.status_code == 200, answered.text
    return dict(answered.json())


# ------------------------------------------------------------------------------------------
# AC-28
# ------------------------------------------------------------------------------------------


async def test_ac28_the_item_carries_the_demuxer_list_and_the_source_resolves_it(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """One `.mp4`, two answers, on one response.

    The item-level string is the whole six-name family and the source's is `mp4`, resolved from
    the file's own extension with no profile involved `[probe:
    tools/probe_media_container.py, Jellyfin 10.11.11, 2026-08-29]`. A server that stored a single
    "resolved container" would have to send the same string twice and be wrong once.
    """
    body = await body_of(client, served[1].of(DIRECT_PLAY).id)

    assert body["Container"] == DIRECT_PLAY.demuxers
    assert "," in body["Container"], "the entry that makes this test discriminating has changed"
    assert [one["Container"] for one in body["MediaSources"]] == ["mp4"]


async def test_a_matroska_file_answers_one_name_at_both_levels(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """The other half of the same rule, and the half the first draft of the spec had backwards:
    `matroska,webm` is normalised to `mkv` at inspection, and a single name is not resolved
    again."""
    body = await body_of(client, served[1].of(REJECTED_CONTAINER).id)

    assert body["Container"] == "mkv"
    assert [one["Container"] for one in body["MediaSources"]] == ["mkv"]


# ------------------------------------------------------------------------------------------
# One source per part
# ------------------------------------------------------------------------------------------


async def test_a_two_part_film_answers_two_sources_in_part_order(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """Spec section 3.1, over the two files 003 merged into one item.

    Asserted on the *runtimes* rather than only on the count: the two parts are deliberately
    different lengths, so "the sources came back in part order" cannot pass on two files a reader
    could not tell apart.
    """
    item = served[1].of(TWO_PARTER_FIRST)
    assert item.id == served[1].of(TWO_PARTER_SECOND).id, "003 stopped merging the parts"

    body = await body_of(client, item.id)
    sources = body["MediaSources"]

    assert [one["Name"] for one in sources] == [
        Path(TWO_PARTER_FIRST.path).stem,
        Path(TWO_PARTER_SECOND.path).stem,
    ]
    assert sources[0]["Id"] == item.id, "part zero is the item, as the reference has it"
    assert sources[1]["Id"] != sources[0]["Id"]
    assert sources[0]["RunTimeTicks"] != sources[1]["RunTimeTicks"], (
        "the two parts measured the same length, so the order assertion proves nothing"
    )


# ------------------------------------------------------------------------------------------
# The streams, and the properties derived from them
# ------------------------------------------------------------------------------------------


async def test_the_streams_on_the_wire_are_the_streams_in_the_file(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """The matrix declares what it encoded; the wire has to say the same thing.

    Compared against the fixture's own declaration rather than against a number written twice -
    the 007 T4 pattern - so a matrix entry that quietly stopped producing `h264` fails here.
    """
    body = await body_of(client, served[1].of(DIRECT_PLAY).id)
    streams = body["MediaStreams"]

    video = next(one for one in streams if one["Type"] == "Video")
    audio = next(one for one in streams if one["Type"] == "Audio")

    assert video["Codec"] == DIRECT_PLAY.video_codec
    assert (video["Width"], video["Height"]) == (DIRECT_PLAY.width, DIRECT_PLAY.height)
    assert audio["Codec"] == DIRECT_PLAY.audio_codec
    assert audio["SampleRate"] == DIRECT_PLAY.sample_rate
    assert audio["Channels"] == DIRECT_PLAY.channels
    assert (body["Width"], body["Height"]) == (DIRECT_PLAY.width, DIRECT_PLAY.height)
    assert body["MediaSources"][0]["MediaStreams"] == streams, (
        "the item-level list is part zero's, and these disagreed"
    )


async def test_a_source_carries_an_etag_and_it_is_the_files_modification_time(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """Derived rather than stored, so it has to survive the round trip through the database.

    Recomputed here from the file on disk: the assembly reads `mtime_ns` out of `item_sources`,
    and a scan that recorded a different one would produce a tag no client could match against
    the file it downloads.
    """
    from atrium.media.info import media_etag

    world = served[1]
    item = world.of(DIRECT_PLAY)
    body = await body_of(client, item.id)

    on_disk = world.files.path_of(DIRECT_PLAY).stat().st_mtime_ns
    assert body["MediaSources"][0]["ETag"] == media_etag(on_disk)


async def test_a_bare_row_of_a_film_carries_the_three_ungated_media_properties(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """`Container`, `VideoType` and - where it is true - `HasSubtitles`, with no `fields` at all.

    This entry carries no subtitle track, so it asserts the *absent* half of the conditional pair;
    the present half is the entry that does, two tests below.
    """
    answered = await client.get("/Items", params={"ids": served[1].of(DIRECT_PLAY).id})
    assert answered.status_code == 200
    row = answered.json()["Items"][0]

    assert row["Container"] == DIRECT_PLAY.demuxers
    assert row["VideoType"] == "VideoFile"
    assert "HasSubtitles" not in row, (
        "this entry gained a subtitle track and is no longer the absent half of the pair"
    )
    assert "MediaSources" not in row, "MediaSources is gated and nothing asked for it"


async def test_a_subtitle_track_reaches_the_wire_under_the_renamed_spelling(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """The file says `hdmv_pgs_subtitle`; the wire says `PGSSUB`, and 008 stored the first.

    Compared against the fixture's own declaration put through the rename table, so the assertion
    is "the file has this track and the wire renames it" rather than a string written twice. The
    flags come along because the matrix split them deliberately between the two tracks: a track's
    properties cannot be attributed to the wrong stream and pass.
    """
    from atrium.media.probe import RENAMED_SUBTITLE_CODECS

    body = await body_of(client, served[1].of(BOTH_SUBTITLE_KINDS).id)
    subtitles = [one for one in body["MediaStreams"] if one["Type"] == "Subtitle"]

    assert len(subtitles) == len(BOTH_SUBTITLE_KINDS.subtitles)
    for declared, wire in zip(BOTH_SUBTITLE_KINDS.subtitles, subtitles, strict=True):
        assert wire["Codec"] == RENAMED_SUBTITLE_CODECS.get(declared.codec, declared.codec)
        assert wire["Language"] == declared.language
        assert wire["Title"] == declared.title
        assert wire["IsForced"] == declared.forced
        assert wire["IsHearingImpaired"] == declared.hearing_impaired
        assert not wire["IsExternal"]

    assert [one["Codec"] for one in subtitles] == ["subrip", "PGSSUB"], (
        "the matrix stopped carrying one text track and one image track"
    )


async def test_the_two_file_facts_are_answered_on_every_stream_of_every_kind(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """AC-1's first half, over a file that was really scanned.

    The text track and the image track differ in the first fact and agree on the second, because
    a Presentation Graphic Stream is servable on its own - which is where "not text" and "not
    servable" come apart, measured as `DVDSUB` answering `false` to the second on a real library
    `[probe: tools/probe_sidecar_subtitles.py, Jellyfin 10.11.11, 2026-08-30]`. And every video and
    audio stream in the file answers `false` to both, which is what the reference does rather than
    leaving them off a stream they cannot describe.
    """
    body = await body_of(client, served[1].of(BOTH_SUBTITLE_KINDS).id)
    by_codec = {one["Codec"]: one for one in body["MediaStreams"]}

    assert by_codec["subrip"]["IsTextSubtitleStream"] is True
    assert by_codec["PGSSUB"]["IsTextSubtitleStream"] is False
    assert by_codec["subrip"]["SupportsExternalStream"] is True
    assert by_codec["PGSSUB"]["SupportsExternalStream"] is True

    for stream in body["MediaStreams"]:
        if stream["Type"] == "Subtitle":
            continue
        assert stream["IsTextSubtitleStream"] is False
        assert stream["SupportsExternalStream"] is False

    assert body["MediaSources"][0]["MediaStreams"] == body["MediaStreams"], (
        "the source's list and the item's disagreed about the same file"
    )


async def test_a_row_of_a_subtitled_film_says_so(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """The present half of the conditional pair the entry above asserts absent, now that the
    matrix has a file with a subtitle track in it."""
    answered = await client.get("/Items", params={"ids": served[1].of(BOTH_SUBTITLE_KINDS).id})
    assert answered.status_code == 200
    assert answered.json()["Items"][0]["HasSubtitles"] is True


async def test_a_track_carries_a_container_and_no_video_properties(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """The per-type split: a container on all three file-backed types, `VideoType` on the two
    that carry video `[source: Emby.Server.Implementations/Dto/DtoService.cs:832,1101-1110 @
    v10.11.11]`."""
    track = next(one for one in served[1].items.values() if one.type is ItemType.AUDIO)
    body = await body_of(client, track.id)

    assert body["Container"] == "flac"
    assert body["MediaSources"][0]["Container"] == "flac"
    for absent in ("VideoType", "Width", "Height", "IsHD"):
        assert absent not in body, f"{absent} on a track, which has no video stream"
