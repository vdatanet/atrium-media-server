# SPDX-License-Identifier: GPL-3.0-or-later
"""The master playlist's subtitle half, over HTTP, followed to the cues it promises.

011 T11. What is asserted here is what a client receives: the `#EXT-X-MEDIA` block, the group on
**every** variant line, the four address classes that must leave the manifest exactly as it was,
and AC-8's traversal - which follows the addresses rather than reading them, because a manifest
and a playlist can both be well formed and lead nowhere (spec sections 3.4 and 3.7).

**One lever, and it is the delivery method alone.** `EnableSubtitlesInManifest` is not bound and
must not be: the route does not accept it on the reference either, so the parameter the
reference's own negotiation writes into the address changes nothing. And the *index* is not part
of the lever, which both documents had the other way round until this task measured it -
`SubtitleMethod=Hls` on its own announces every text track, and the index decides which entry
carries `DEFAULT=YES` and nothing else `[probe: manual requests via tools/_probe.py, Jellyfin
10.11.11, 2026-08-30]`.

**Every address here is followed rather than rebuilt.** The negotiation writes the address, the
master is fetched from it, each announcement is resolved against the master's own directory with
`httpx.URL.join`, and each playlist entry against the playlist's - so the lower-case `stream.vtt`
an entry names is asked for exactly as written, which is AC-8's whole point.

`[probe: tools/probe_subtitle_manifest.py, Jellyfin 10.11.11, 2026-08-29]` is the measurement
behind the anatomy of an entry; the multi-variant case and the vocabulary are `[probe: manual
requests via tools/_probe.py, Jellyfin 10.11.11, 2026-08-30]`.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI, Request

from atrium.api.deps import require_user
from atrium.config.paths import DataPaths
from atrium.db.repositories import UserRepository
from atrium.domain.user import User
from atrium.media import hls, subtitles
from atrium.media.labels import media_type_of
from atrium.server import create_app
from tests.conformance.test_golden import STATE
from tests.fixtures.media import (
    BOTH_SUBTITLE_KINDS,
    CUES,
    HIGH_RANGE,
    LONG_TAKE,
    SIDECAR_CUES,
    UNCONVERTIBLE_SUBTITLE,
    BuiltMedia,
    MediaFile,
    SidecarFile,
    generate,
)
from tests.fixtures.media_world import ScannedMediaWorld, build_scanned_media_world

pytestmark = [pytest.mark.conformance, pytest.mark.ffmpeg]

VIEWER_ID = "e" * 32
TOKEN = "0123456789abcdef0123456789abcdef"
HEADERS = {"X-Emby-Token": TOKEN}

PLAYLIST_TYPE = media_type_of("m3u8")

#: An HDR film with a text subtitle track, which is the only shape that can answer AC-5's second
#: half: the master carries an SDR entrance beside a stream copy **only** for a high-dynamic-range
#: source, and it carries a subtitle group only for a source with a text track. No matrix entry
#: has both, and neither of the two that have one can gain the other - `high_range` has to be mp4
#: because the Matroska muxer drops its colour statement, and mp4 accepts neither of the two image
#: subtitle codecs. So the track arrives **beside** the file rather than inside it, which costs
#: nothing here and exercises an external stream's announcement into the bargain.
SUBTITLED_HIGH_RANGE: MediaFile = replace(
    HIGH_RANGE,
    key="subtitled_high_range",
    path="The Subtitled High Range (2007)/The Subtitled High Range (2007).mp4",
    sidecars=(
        SidecarFile(
            name="The Subtitled High Range (2007).eng.srt",
            reason="011 AC-5: the group belongs on the SDR entrance too, and an entrance with no "
            "subtitles is the client the entrance exists for losing them",
        ),
    ),
)

#: The profile that reaches a manifest: nothing direct-plays, the transcode is HLS, and the one
#: subtitle entry asks for the manifest method. `vtt` rather than the track's own spelling on
#: purpose - the ladder's fourth pass is the one that converts, and it is the pass a real client
#: reaches (011 plan section 6.3).
MANIFEST_PROFILE: dict[str, Any] = {
    "MaxStreamingBitrate": 120_000_000,
    "DirectPlayProfiles": [{"Container": "nothingatall", "Type": "Video"}],
    "TranscodingProfiles": [
        {
            "Container": "ts",
            "Type": "Video",
            "VideoCodec": "h264",
            "AudioCodec": "aac",
            "Protocol": "hls",
            "Context": "Streaming",
            "MinSegments": 1,
            "BreakOnNonKeyFrames": True,
        }
    ],
    "CodecProfiles": [],
    "ContainerProfiles": [],
    "SubtitleProfiles": [{"Format": "vtt", "Method": "Hls"}],
}

#: The same profile against a file whose *audio* is what fails, so the video is copied - which is
#: the only way to an SDR entrance. `high_range` is h264 beside ac3, and flac is a codec it has
#: not got, so direct play is refused on the audio and the transcode copies the video.
COPY_THE_VIDEO: dict[str, Any] = {
    **MANIFEST_PROFILE,
    "DirectPlayProfiles": [
        {"Container": "mp4", "Type": "Video", "VideoCodec": "h264", "AudioCodec": "flac"}
    ],
}


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
def with_subtitled_hdr(media_files: BuiltMedia, tmp_path: Path) -> BuiltMedia:
    """The generated matrix plus the subtitled HDR film, in a tree this test may write to.

    Generated here rather than declared in the matrix for the reason `test_hls_playlists.py` adds
    its Matroska sibling here: one file that one module needs does not belong in a matrix every
    other module regenerates.
    """
    copied = media_files.copy_into(tmp_path / "media")
    generate(SUBTITLED_HIGH_RANGE, copied.base)
    return copied


@pytest.fixture
def served(
    media_paths: DataPaths, with_subtitled_hdr: BuiltMedia
) -> Iterator[tuple[FastAPI, ScannedMediaWorld]]:
    built = create_app(media_paths)
    built.state.readiness.mark_ready()
    with built.state.sessions.begin() as opened:
        world = build_scanned_media_world(opened, with_subtitled_hdr)
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


# ------------------------------------------------------------------------------------------
# Reading the world the way a client does
# ------------------------------------------------------------------------------------------


async def streams_of(client: httpx.AsyncClient, item_id: str) -> list[dict[str, Any]]:
    """The source's streams as a client reads them, which is where the **wire** index is."""
    answered = await client.get(f"/Items/{item_id}", headers=HEADERS)
    assert answered.status_code == 200, answered.text
    sources = answered.json()["MediaSources"]
    streams: list[dict[str, Any]] = sources[0]["MediaStreams"]
    return streams


async def index_of(client: httpx.AsyncClient, item_id: str, codec: str) -> int:
    """The wire index of the one subtitle stream in this source with this codec."""
    found = [
        one
        for one in await streams_of(client, item_id)
        if one["Type"] == "Subtitle" and str(one.get("Codec", "")).lower() == codec.lower()
    ]
    assert len(found) == 1, f"{codec}: expected one subtitle stream, found {len(found)}"
    return int(found[0]["Index"])


async def negotiated_address(
    client: httpx.AsyncClient,
    item_id: str,
    profile: dict[str, Any],
    **body: Any,
) -> str:
    """The `TranscodingUrl` a negotiation hands back, which is the address a client follows.

    Not rebuilt here: the whole of this feature's manifest half is a client following an address
    it was given, so a test that wrote its own would be testing a different request.
    """
    answered = await client.post(
        f"/Items/{item_id}/PlaybackInfo",
        json={"DeviceProfile": profile, "MediaSourceId": item_id, **body},
        headers=HEADERS,
    )
    assert answered.status_code == 200, answered.text
    url = answered.json()["MediaSources"][0]["TranscodingUrl"]
    assert url and "master.m3u8" in url, f"the negotiation planned no HLS transcode: {url!r}"
    return str(url)


def announcements(playlist: str) -> list[str]:
    return [line for line in playlist.splitlines() if line.startswith("#EXT-X-MEDIA:")]


def variants(playlist: str) -> list[str]:
    return [line for line in playlist.splitlines() if line.startswith("#EXT-X-STREAM-INF")]


def attribute(line: str, name: str) -> str:
    """One attribute of an `#EXT-X-MEDIA` line, quotes stripped. Written by hand rather than
    parsed, because the exact spelling is the thing under test."""
    rest = line.split(name + "=", 1)[1]
    if rest.startswith('"'):
        return rest[1 : rest.index('"', 1)]
    return rest.split(",", 1)[0]


async def master_for(client: httpx.AsyncClient, address: str) -> httpx.Response:
    answered = await client.get(address, headers=HEADERS)
    assert answered.status_code == 200, answered.text
    return answered


async def follow(client: httpx.AsyncClient, base: str, relative: str) -> httpx.Response:
    """One hop, resolved the way a player resolves it: against the document's own directory."""
    return await client.get(str(httpx.URL(base).join(relative)), headers=HEADERS)


def texts(body: bytes, target_format: str = "vtt") -> list[str]:
    return [cue.text for cue in subtitles.parse(body.decode("utf-8-sig"), target_format)]


# ------------------------------------------------------------------------------------------
# AC-5: what is announced, and where the group goes
# ------------------------------------------------------------------------------------------


async def test_ac5_an_announcement_is_the_measured_line_verbatim(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """The whole `#EXT-X-MEDIA` line, byte for byte, against the address the negotiation wrote.

    Every attribute is pinned: the order, the literal group, `AUTOSELECT=YES` on every entry, the
    hard-coded thirty-second window, the caller's own token in the address, and the `NAME` this
    project writes in the invariant form - which is the one attribute 011 knowingly diverges on
    (spec section 3.2) and is therefore written out here rather than computed by the module that
    produces it.
    """
    item = served[1].of(BOTH_SUBTITLE_KINDS)
    index = await index_of(client, item.id, "subrip")

    address = await negotiated_address(client, item.id, MANIFEST_PROFILE, SubtitleStreamIndex=index)
    assert f"SubtitleStreamIndex={index}" in address, "the negotiation dropped the index"
    assert "SubtitleMethod=Hls" in address, "the negotiation named no manifest method"

    answered = await master_for(client, address)

    assert answered.headers["Content-Type"] == PLAYLIST_TYPE
    assert answered.headers["Content-Length"] == str(len(answered.content))
    assert answered.headers["Expires"] == "0"
    lines = answered.text.splitlines()
    assert lines[0] == "#EXTM3U"
    assert lines[1] == (
        '#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",'
        'NAME="Plain Cues - English - Default - SUBRIP",'
        "DEFAULT=YES,FORCED=NO,AUTOSELECT=YES,"
        f'URI="{item.id}/Subtitles/{index}/subtitles.m3u8?SegmentLength=30&ApiKey={TOKEN}",'
        'LANGUAGE="eng"'
    ), "the announcement is not the measured shape"
    assert lines[2].startswith("#EXT-X-STREAM-INF:"), "the block goes before the first variant"
    assert lines[2].endswith(',SUBTITLES="subs"'), "the group is last, after the frame rate"


async def test_ac5_every_variant_of_a_multi_variant_master_ends_in_the_group(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """**The finding the tasks gate caught, asserted where it can fail.**

    An HDR source whose video is copied is offered a standard-range entrance beside the copy, and
    that entrance exists precisely so a client which cannot render the copy has somewhere to go.
    Written as "the variant line gains the group", the entrance would be the one variant offering
    no subtitles - to exactly that client. The reference hands its group to every playlist line it
    appends, measured on the wire against an HDR film copied for a client: three variants there
    (the operator has an encoder Atrium has no knob for), all three ending `,SUBTITLES="subs"`.
    """
    item = served[1].of(SUBTITLED_HIGH_RANGE)
    index = await index_of(client, item.id, "subrip")

    address = await negotiated_address(client, item.id, COPY_THE_VIDEO, SubtitleStreamIndex=index)
    answered = await master_for(client, address)

    lines = variants(answered.text)
    assert len(lines) == 2, "an HDR copy is offered an SDR entrance beside it (008 T15)"
    assert "VIDEO-RANGE=PQ" in lines[0] and "VIDEO-RANGE=SDR" in lines[1]
    for line in lines:
        assert line.endswith(',SUBTITLES="subs"'), f"a variant with no subtitle group: {line}"
        assert "FRAME-RATE=" in line.rsplit(",SUBTITLES=", 1)[0], "the group goes after the rate"
    assert len(announcements(answered.text)) == 1


async def test_a_sidecars_announcement_carries_the_external_word_and_its_own_language(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """A track discovered beside the film is announced like one inside it, at its wire index.

    Measured on the reference, where a source's external text tracks are announced at indices
    0, 1 and 2 - ahead of the container's own - with the external word in the name.
    """
    item = served[1].of(SUBTITLED_HIGH_RANGE)
    index = await index_of(client, item.id, "subrip")

    address = await negotiated_address(client, item.id, COPY_THE_VIDEO, SubtitleStreamIndex=index)
    answered = await master_for(client, address)

    entry = announcements(answered.text)[0]
    assert index == 0, "an external stream is numbered ahead of the container's own (T3)"
    assert attribute(entry, "NAME") == "English - SUBRIP - External"
    assert attribute(entry, "LANGUAGE") == "eng"
    assert attribute(entry, "URI").startswith(f"{item.id}/Subtitles/0/subtitles.m3u8")


# ------------------------------------------------------------------------------------------
# AC-6: the four classes that must change nothing
# ------------------------------------------------------------------------------------------


async def test_ac6_a_request_that_names_no_manifest_method_answers_the_same_bytes(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """The criterion that keeps 008's answer intact, on a film that **has** a text track - so a
    manifest that announced one would be caught rather than trivially absent.

    The comparison is byte-for-byte against the master the same request answers without the extra
    parameter, with the one difference that must exist: a variant's URI is the query string
    verbatim, so the parameter appears there and nowhere else.
    """
    item = served[1].of(BOTH_SUBTITLE_KINDS)
    index = await index_of(client, item.id, "subrip")
    address = await negotiated_address(client, item.id, MANIFEST_PROFILE)
    assert "SubtitleMethod" not in address, "no track was selected, so no method is written"
    base = (await master_for(client, address)).text
    assert len(variants(base)) == 1, "the comparison below assumes the single-variant shape"

    unchanged = {
        "the manifest flag": "&EnableSubtitlesInManifest=true",
        "an index with no method": f"&SubtitleStreamIndex={index}",
        "the external method": f"&SubtitleStreamIndex={index}&SubtitleMethod=External",
        "the burn-in method": f"&SubtitleStreamIndex={index}&SubtitleMethod=Encode",
        # Measured beside the four, and neither of them refuses: a word that is no member of the
        # vocabulary announces nothing, where the same word on a request body is a `400`.
        "a method that is no member": f"&SubtitleStreamIndex={index}&SubtitleMethod=banana",
        "the drop method": f"&SubtitleStreamIndex={index}&SubtitleMethod=Drop",
    }
    query = address.split("master.m3u8", 1)[1]
    for label, extra in unchanged.items():
        answered = await master_for(client, address + extra)

        assert answered.text == base.replace(query, query + extra), (
            f"{label}: the master differs from the one the same request answers without it, "
            f"beyond the variant's own echo of the query string"
        )
        assert not announcements(answered.text), label
        assert "SUBTITLES=" not in answered.text, label


async def test_a_source_with_no_text_subtitle_stream_is_never_given_a_group(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """The other half of the reference's own condition: a group needs a text track to point at."""
    item = served[1].of(LONG_TAKE)
    address = await negotiated_address(client, item.id, MANIFEST_PROFILE)

    answered = await master_for(client, address + "&SubtitleStreamIndex=0&SubtitleMethod=Hls")

    assert not announcements(answered.text)
    assert "SUBTITLES=" not in answered.text


# ------------------------------------------------------------------------------------------
# AC-7: the filter is on the stream kind, not on the selection
# ------------------------------------------------------------------------------------------


async def test_ac7_an_image_index_still_announces_every_text_track_with_no_default(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """Selecting an image track announces every **text** track, with `DEFAULT=NO` on all of them.

    It falls out of comparing indices rather than being a case: no announced stream matches the
    selected one, so nothing is the default. The same answer as an index naming no stream at all,
    and as no index at all - the three are one branch, measured.
    """
    item = served[1].of(BOTH_SUBTITLE_KINDS)
    text = await index_of(client, item.id, "subrip")
    image = await index_of(client, item.id, "PGSSUB")
    address = await negotiated_address(client, item.id, MANIFEST_PROFILE)

    for label, selected in (("an image index", image), ("an index naming nothing", 99)):
        answered = await master_for(
            client, f"{address}&SubtitleStreamIndex={selected}&SubtitleMethod=Hls"
        )

        entries = announcements(answered.text)
        assert len(entries) == 1, f"{label}: the image track was announced or the text one was not"
        assert attribute(entries[0], "URI").startswith(f"{item.id}/Subtitles/{text}/")
        assert [attribute(one, "DEFAULT") for one in entries] == ["NO"], label
        assert variants(answered.text)[0].endswith(',SUBTITLES="subs"'), label


# ------------------------------------------------------------------------------------------
# The lever, and the vocabulary T11 owed
# ------------------------------------------------------------------------------------------


async def test_the_method_binds_in_any_case_and_by_ordinal_and_refuses_nothing(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """011 plan section 6.8's owed row, measured on the master playlist route.

    Seven spellings announce and seven do not, and **none of the fourteen refuses** - which is the
    half that does not carry across from the same word on a request body, where a word that is no
    member is a `400`. Jellyfin binds a nullable enum parameter through a binder that catches the
    conversion failure and leaves the value unset.

    The two comma lists are the discriminating pair: `Embed,External` is `1 | 2`, which is the
    manifest method's own ordinal, so it announces where `External,External` announces nothing -
    and a server reading only the first name would answer the opposite on both.
    """
    item = served[1].of(BOTH_SUBTITLE_KINDS)
    index = await index_of(client, item.id, "subrip")
    address = await negotiated_address(client, item.id, MANIFEST_PROFILE)

    for spelling in ("Hls", "hls", "HLS", "hLs", "3", "Embed%2CExternal", "1%2C2"):
        answered = await master_for(
            client, f"{address}&SubtitleStreamIndex={index}&SubtitleMethod={spelling}"
        )
        assert len(announcements(answered.text)) == 1, spelling
        assert attribute(announcements(answered.text)[0], "DEFAULT") == "YES", spelling

    for spelling in ("banana", "9", "", "3.0", "--3", "External%2CExternal", "Hls%2Cbanana"):
        answered = await master_for(
            client, f"{address}&SubtitleStreamIndex={index}&SubtitleMethod={spelling}"
        )
        assert not announcements(answered.text), spelling
        assert "SUBTITLES=" not in answered.text, spelling


async def test_the_index_is_not_part_of_the_lever_and_only_decides_the_default(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """**What both documents had the other way round.**

    Spec section 3.4 said the announcement needs the manifest method *beside a stream index*.
    Measured, the method alone announces every text track: with no index at all, with `-1`, and
    with an index naming no stream. That matters to the client this feature exists for, which
    rewrites the address it was handed rather than re-negotiating - an implementation requiring
    both would have announced nothing to a client that sent one.
    """
    item = served[1].of(BOTH_SUBTITLE_KINDS)
    address = await negotiated_address(client, item.id, MANIFEST_PROFILE)

    for label, extra in (
        ("no index at all", "&SubtitleMethod=Hls"),
        ("the index -1", "&SubtitleStreamIndex=-1&SubtitleMethod=Hls"),
    ):
        answered = await master_for(client, address + extra)

        entries = announcements(answered.text)
        assert len(entries) == 1, label
        assert attribute(entries[0], "DEFAULT") == "NO", label
        assert variants(answered.text)[0].endswith(',SUBTITLES="subs"'), label


async def test_an_index_that_is_not_a_number_is_the_frameworks_refusal(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """The asymmetry beside the row above: the *index* is typed and the *method* is not, so one of
    the two refuses a value it cannot read and the other ignores it. Both measured in one run."""
    item = served[1].of(BOTH_SUBTITLE_KINDS)
    address = await negotiated_address(client, item.id, MANIFEST_PROFILE)

    answered = await client.get(
        f"{address}&SubtitleStreamIndex=banana&SubtitleMethod=Hls", headers=HEADERS
    )

    assert answered.status_code == 400
    assert "subtitleStreamIndex" in answered.text


# ------------------------------------------------------------------------------------------
# AC-4 and AC-8: the address names the track, and every address leads somewhere
# ------------------------------------------------------------------------------------------


async def test_ac4_the_index_in_the_address_selects_the_track_that_is_served(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """The criterion the video client's contract asks for, in its subtitle half.

    `The Unconvertible` carries two text tracks with different cues - one inside the container and
    one beside it - so "the track the address named" is a claim that can fail. Each index is asked
    for in turn, and the cues that come back at the end of the traversal are that track's.
    """
    item = served[1].of(UNCONVERTIBLE_SUBTITLE)
    inside = await index_of(client, item.id, "ass")
    beside = await index_of(client, item.id, "subrip")
    address = await negotiated_address(client, item.id, MANIFEST_PROFILE)

    for index, expected in ((inside, CUES), (beside, SIDECAR_CUES)):
        master = await master_for(
            client, f"{address}&SubtitleStreamIndex={index}&SubtitleMethod=Hls"
        )

        entries = announcements(master.text)
        assert len(entries) == 2, "both text tracks are announced whatever the selection is"
        chosen = [one for one in entries if attribute(one, "DEFAULT") == "YES"]
        assert len(chosen) == 1, f"index {index} marked {len(chosen)} entries as the default"
        assert attribute(chosen[0], "URI").startswith(f"{item.id}/Subtitles/{index}/")

        playlist = await follow(client, str(master.url), attribute(chosen[0], "URI"))
        assert playlist.status_code == 200, playlist.text
        window = next(
            line for line in playlist.text.splitlines() if not line.startswith("#") and line
        )
        cues = await follow(client, str(playlist.url), window)

        assert cues.status_code == 200, cues.text
        assert texts(cues.content) == [cue.text for cue in expected], (
            f"index {index} was announced and a different track was served"
        )


async def test_ac8_every_announced_address_and_every_window_is_fetched_as_written(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """**A traversal, not a string comparison.**

    The playlist route never reads the index it is given, so a manifest and a playlist can both be
    well formed and lead nowhere - a `200` listing a hundred addresses, every one of which answers
    `500`. Only following them says so. Every hop here is resolved as written, which includes the
    lower-case `stream.vtt` an entry names where the route is declared `Stream.{format}`.

    **The track the negotiation is asked for is the sidecar and not the `ass` one**, and that is
    the ladder rather than a choice here: `ass` can be converted neither from nor to, so it
    answers `Encode` under a `vtt`-only profile and no manifest method is written (AC-3). It is
    still *announced* - the filter is on the stream kind - so the traversal walks it anyway, which
    is the point: an announcement leads somewhere or it does not, whatever was selected.
    """
    item = served[1].of(UNCONVERTIBLE_SUBTITLE)
    index = await index_of(client, item.id, "subrip")
    address = await negotiated_address(client, item.id, MANIFEST_PROFILE, SubtitleStreamIndex=index)
    master = await master_for(client, address)

    entries = announcements(master.text)
    assert entries, "nothing was announced, so this test would pass by iterating over nothing"
    followed = 0
    for entry in entries:
        uri = attribute(entry, "URI")
        playlist = await follow(client, str(master.url), uri)

        assert playlist.status_code == 200, f"{uri} -> {playlist.status_code}"
        assert playlist.headers["Content-Type"] == PLAYLIST_TYPE
        windows = [line for line in playlist.text.splitlines() if line and not line.startswith("#")]
        assert windows, f"{uri} answered a playlist with no windows"
        for window in windows:
            assert window.startswith("stream.vtt?"), window
            cues = await follow(client, str(playlist.url), window)

            assert cues.status_code == 200, f"{uri} -> {window} -> {cues.status_code}"
            assert cues.content, f"{uri} -> {window} answered an empty body"
            assert texts(cues.content), f"{uri} -> {window} answered a document with no cues"
            followed += 1
    assert followed == len(entries), "one window per four-second track, at a thirty-second window"


async def test_the_announced_address_carries_the_callers_own_token(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """The token is load-bearing rather than decorative: the playlist route requires a caller and
    a player following a `URI` out of a manifest sends no headers of its own.

    It comes from `compat/auth.extract_token` and not from `request.state`, which holds the digest
    of it and nothing else.
    """
    item = served[1].of(BOTH_SUBTITLE_KINDS)
    address = await negotiated_address(client, item.id, MANIFEST_PROFILE)

    answered = await master_for(client, f"{address}&SubtitleMethod=Hls")

    uri = attribute(announcements(answered.text)[0], "URI")
    assert uri.endswith(f"?SegmentLength={hls.ANNOUNCED_WINDOW_SECONDS}&ApiKey={TOKEN}")


async def test_a_caller_with_no_token_writes_an_empty_one_rather_than_omitting_it(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """What the reference's own `string.Format` of a null does, reproduced: the parameter stays
    and its value is empty, which is what the subtitle playlist's own entries already do.

    **Reaching it takes work, and that is the finding rather than the assertion.** A negotiated
    address carries the caller's token in its own query string (008's `ApiKey`), so a request that
    sends no header still presents one - which is why the announced address is credentialled on
    every path a client actually walks. The parameter is stripped here to reach the branch at all.
    """
    item = served[1].of(BOTH_SUBTITLE_KINDS)
    address = await negotiated_address(client, item.id, MANIFEST_PROFILE)
    anonymous = "&".join(
        pair for pair in address.split("&") if not pair.startswith(("ApiKey=", "api_key="))
    )
    assert anonymous != address, "the negotiated address carried no token to strip"

    answered = await client.get(f"{anonymous}&SubtitleMethod=Hls")

    assert answered.status_code == 200, answered.text
    assert attribute(announcements(answered.text)[0], "URI").endswith("&ApiKey=")
