# SPDX-License-Identifier: GPL-3.0-or-later
"""`static=true`: the original bytes, over HTTP, from a file a demuxer can really open.

The four `stream` routes' static half is delivery with no process behind it, which makes it the
place three rules get proven before ffmpeg can complicate them: the range matrix, the
`Content-Type`-label rule, and - the one this task measured and found reversed - that these routes
want no credential at all.

Every case runs against 008 T1's generated matrix, scanned by the real 003 pipeline and served
through the real application, because "the untouched original bytes" is only a claim if there are
original bytes to compare against. `tests/unit/test_compat_ranges.py` owns the matrix over the
whole number line; what is proven here is that a real response carries them, with the exact header
set the reference sends and nothing beside it.

`[probe: tools/probe_range_matrix.py, Jellyfin 10.11.11, 2026-08-29]` is the measurement behind
every assertion in this file.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI, Request

from atrium.api.deps import require_user
from atrium.compat.errors import CONTROLLER_ERROR_BODY, PATTERN_MESSAGE
from atrium.config.paths import DataPaths
from atrium.db.repositories import UserRepository
from atrium.domain.user import User
from atrium.media.labels import MEDIA_TYPES
from atrium.server import create_app
from tests.conformance.test_golden import STATE
from tests.fixtures.media import (
    DIRECT_PLAY,
    HIGH_RATE_AUDIO,
    REJECTED_CONTAINER,
    BuiltMedia,
    MediaFile,
)
from tests.fixtures.media_world import ScannedMediaWorld, build_scanned_media_world

pytestmark = [pytest.mark.conformance, pytest.mark.ffmpeg]

VIEWER_ID = "e" * 32

#: A token nothing issued, sent to prove the routes do not validate what they do not require.
UNKNOWN_TOKEN = "0123456789abcdef0123456789abcdef"

#: An identifier no scan produced.
UNKNOWN_ITEM = "deadbeefdeadbeefdeadbeefdeadbeef"

#: What the first bytes of each generated container look like, read independently of anything
#: under test: a `206` that "serves the original bytes" is only an assertion if something knows
#: what the original bytes are.
MAGIC = {
    "mp4": (4, b"ftyp"),
    "matroska": (0, b"\x1a\x45\xdf\xa3"),
    "flac": (0, b"fLaC"),
}

#: The complete set the reference sends on a static answer, measured. Absences are the point: no
#: `ETag`, no `Content-Disposition`, no `Cache-Control`, no `Vary` - the framework's file response
#: would have added two of them.
STATIC_HEADERS = {"content-length", "content-type", "accept-ranges", "last-modified"}

#: What 001's middleware puts on every response, delivery included. Excluded from the set above so
#: this file asserts the route's own headers rather than re-asserting 001's.
ALWAYS = {"server", "x-response-time-ms"}


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
    """The real application over the real scan, the shape 008 T5 established."""
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

    Without this the credential tests would be vacuous: an override that hands back a user makes
    every route look tokenless-friendly, including the ones that are not.
    """
    served[0].dependency_overrides.clear()
    transport = httpx.ASGITransport(app=served[0])
    async with httpx.AsyncClient(transport=transport, base_url="http://atrium:8096") as opened:
        yield opened


def film(served: tuple[FastAPI, ScannedMediaWorld], entry: MediaFile) -> tuple[str, bytes, int]:
    """The item id behind a generated file, its bytes, and its size - read from disk directly."""
    item = served[1].of(entry)
    path = served[1].files.path_of(entry)
    payload = path.read_bytes()
    return item.id, payload, len(payload)


# ------------------------------------------------------------------------------------------
# The range matrix, over HTTP - AC-11 through AC-14
# ------------------------------------------------------------------------------------------


async def test_ac14_no_range_is_the_whole_file_with_its_length(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """AC-14: a direct-play response carries a `Content-Length` equal to the file size - and the
    body really is the file, byte for byte."""
    item_id, payload, size = film(served, DIRECT_PLAY)

    answered = await client.get(f"/Videos/{item_id}/stream", params={"static": "true"})

    assert answered.status_code == 200
    assert answered.headers["Content-Length"] == str(size)
    assert answered.headers["Accept-Ranges"] == "bytes"  # AC-11
    assert "Content-Range" not in answered.headers
    assert answered.content == payload


async def test_ac12_a_mid_file_range_is_exactly_those_bytes(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """AC-12, measured verbatim: `bytes=100-199` is `206`, `Content-Length: 100`, and the hundred
    bytes at offset 100."""
    item_id, payload, size = film(served, DIRECT_PLAY)

    answered = await client.get(
        f"/Videos/{item_id}/stream", params={"static": "true"}, headers={"Range": "bytes=100-199"}
    )

    assert answered.status_code == 206
    assert answered.headers["Content-Range"] == f"bytes 100-199/{size}"
    assert answered.headers["Content-Length"] == "100"
    assert answered.content == payload[100:200]


@pytest.mark.parametrize(
    ("header", "status"),
    [
        ("bytes=0-49,100-149", 200),
        ("bytes=200-100", 200),
        ("bananas", 200),
        ("bytes=abc-def", 200),
    ],
)
async def test_the_shapes_it_will_not_split_are_the_whole_body(
    client: httpx.AsyncClient,
    served: tuple[FastAPI, ScannedMediaWorld],
    header: str,
    status: int,
) -> None:
    """The measured full-body rows, byte-exact. A multi-range is not split, a reversed range is not
    refused, and neither is any shape of nonsense."""
    item_id, payload, size = film(served, DIRECT_PLAY)

    answered = await client.get(
        f"/Videos/{item_id}/stream", params={"static": "true"}, headers={"Range": header}
    )

    assert answered.status_code == status
    assert answered.headers["Content-Length"] == str(size)
    assert "Content-Range" not in answered.headers
    assert answered.content == payload


@pytest.mark.parametrize("shape", ["past the end", "an empty suffix"])
async def test_ac13_an_unsatisfiable_range_is_a_416_with_nothing_in_it(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld], shape: str
) -> None:
    """AC-13: `Content-Range: bytes */total`, `Content-Length: 0`, and an empty body - with the
    `Content-Type` of the body it declined to send still on it, measured."""
    item_id, _, size = film(served, DIRECT_PLAY)
    header = f"bytes={size}-" if shape == "past the end" else "bytes=-0"

    answered = await client.get(
        f"/Videos/{item_id}/stream", params={"static": "true"}, headers={"Range": header}
    )

    assert answered.status_code == 416
    assert answered.headers["Content-Range"] == f"bytes */{size}"
    assert answered.headers["Content-Length"] == "0"
    assert answered.headers["Content-Type"] == "video/mp4"
    assert answered.headers["Accept-Ranges"] == "bytes"
    assert answered.content == b""


async def test_the_suffix_form_is_the_last_bytes(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    item_id, payload, size = film(served, DIRECT_PLAY)

    answered = await client.get(
        f"/Videos/{item_id}/stream", params={"static": "true"}, headers={"Range": "bytes=-100"}
    )

    assert answered.status_code == 206
    assert answered.headers["Content-Range"] == f"bytes {size - 100}-{size - 1}/{size}"
    assert answered.content == payload[-100:]


async def test_the_response_carries_the_measured_header_set_and_no_more(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """The absences are the assertion. Starlette's `FileResponse` would have added an `ETag` the
    reference never sends, which is how 006's image routes ended up building theirs by hand too."""
    item_id, _, _ = film(served, DIRECT_PLAY)

    answered = await client.get(f"/Videos/{item_id}/stream", params={"static": "true"})

    assert {name.lower() for name in answered.headers} - ALWAYS == STATIC_HEADERS


async def test_a_conditional_request_is_answered_with_the_whole_film(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """Measured: `If-Modified-Since` in the future answers `200`, not `304`. These routes do no
    conditional handling at all, and a server that started would stop serving a client that caches
    what it never asked to cache."""
    item_id, _, size = film(served, DIRECT_PLAY)

    answered = await client.get(
        f"/Videos/{item_id}/stream",
        params={"static": "true"},
        headers={"If-Modified-Since": "Sat, 01 Jan 2028 00:00:00 GMT"},
    )

    assert answered.status_code == 200
    assert answered.headers["Content-Length"] == str(size)


# ------------------------------------------------------------------------------------------
# The label - AC-18 and behaviours section 2.20
# ------------------------------------------------------------------------------------------


async def test_ac18_a_wrong_container_changes_the_label_and_nothing_else(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """AC-18, behaviours section 2.20: `stream.mkv?static=true` on an mp4 film is the mp4 bytes
    behind `video/x-matroska`.

    The body is checked twice over - against the file, and against the container's own magic
    bytes - because "the original bytes" and "not a Matroska file" are two different claims and
    the second is the one a client would notice.
    """
    item_id, payload, _ = film(served, DIRECT_PLAY)

    answered = await client.get(f"/Videos/{item_id}/stream.mkv", params={"static": "true"})

    assert answered.status_code == 200
    assert answered.headers["Content-Type"] == "video/x-matroska"
    assert answered.content == payload
    offset, magic = MAGIC["mp4"]
    assert answered.content[offset : offset + len(magic)] == magic
    assert not answered.content.startswith(MAGIC["matroska"][1])


async def test_the_suffixed_and_unsuffixed_routes_answer_the_same_bytes(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """Byte-identical, ranges included - which is what makes the suffix a label rather than a
    request to convert anything."""
    item_id, _, _ = film(served, DIRECT_PLAY)
    ranged = {"Range": "bytes=0-63"}

    plain = await client.get(f"/Videos/{item_id}/stream", params={"static": "true"}, headers=ranged)
    labelled = await client.get(
        f"/Videos/{item_id}/stream.webm", params={"static": "true"}, headers=ranged
    )

    assert plain.content == labelled.content
    assert plain.headers["Content-Type"] == "video/mp4"
    assert labelled.headers["Content-Type"] == "video/webm"


async def test_the_query_container_is_the_same_lever_as_the_suffix(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """Measured: `?container=mkv` on the unsuffixed route answers `video/x-matroska` over the same
    original bytes."""
    item_id, payload, _ = film(served, DIRECT_PLAY)

    answered = await client.get(
        f"/Videos/{item_id}/stream", params={"static": "true", "container": "mkv"}
    )

    assert answered.headers["Content-Type"] == "video/x-matroska"
    assert answered.content == payload


async def test_a_container_nobody_recognises_falls_back_to_the_file(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """Measured: `stream.banana?static=true` on an mp4 is `video/mp4`. The reference resolves the
    label from the requested container first and from the file's own extension second, so an
    unheard-of container still gets an honest label."""
    item_id, payload, _ = film(served, DIRECT_PLAY)

    answered = await client.get(f"/Videos/{item_id}/stream.banana", params={"static": "true"})

    assert answered.status_code == 200
    assert answered.headers["Content-Type"] == "video/mp4"
    assert answered.content == payload


async def test_a_track_is_labelled_from_the_same_table(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """`stream.wav?static=true` on a flac track: the flac bytes behind `audio/wav`.

    This is the one shape of the reference's PCM/WAV defect that is not broken - static never
    starts an encoder, so the route that answers `500` for a produced WAV (behaviours section 3.2)
    answers the source here.
    """
    item_id, payload, _ = film(served, HIGH_RATE_AUDIO)

    answered = await client.get(f"/Audio/{item_id}/stream.wav", params={"static": "true"})

    assert answered.status_code == 200
    assert answered.headers["Content-Type"] == "audio/wav"
    assert answered.content == payload
    assert answered.content.startswith(MAGIC["flac"][1])


async def test_the_label_table_is_the_measured_one() -> None:
    """Six rows nobody would have written from first principles, pinned so a tidying pass cannot
    quietly correct them into what they ought to be."""
    assert MEDIA_TYPES["mts"] == "model/vnd.mts"
    assert MEDIA_TYPES["mpc"] == "application/vnd.mophun.certificate"
    assert MEDIA_TYPES["rmvb"] == "application/vnd.rn-realmedia-vbr"
    assert MEDIA_TYPES["opus"] == "audio/ogg"
    assert MEDIA_TYPES["alac"] == "audio/mp4"
    assert MEDIA_TYPES["ogv"] == "video/ogg"


# ------------------------------------------------------------------------------------------
# The credential - measured, and the opposite of what this task's statement said
# ------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "route", ["/Videos/{id}/stream", "/Videos/{id}/stream.mkv", "/Audio/{id}/stream"]
)
async def test_a_delivery_route_requires_no_token(
    unauthenticated: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld], route: str
) -> None:
    """Measured on all four routes: no token, an unknown token and `?api_key=` are one answer.

    Behaviours section 2.10 left this decision to 008; 008 T6 measured it and replicates. The
    consequence is the recorded one - an item id is a capability on these routes - and diverging
    would break the bare URL handed to an external player, which is what they are for.
    """
    entry = DIRECT_PLAY if route.startswith("/Videos") else HIGH_RATE_AUDIO
    item_id, payload, _ = film(served, entry)
    path = route.format(id=item_id)

    nothing = await unauthenticated.get(path, params={"static": "true"})
    unknown = await unauthenticated.get(path, params={"static": "true", "api_key": UNKNOWN_TOKEN})

    assert nothing.status_code == 200
    assert unknown.status_code == 200
    assert nothing.content == unknown.content == payload


async def test_the_credential_check_can_still_fail(
    unauthenticated: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """The assertion above is only worth anything if the same client is refused somewhere.

    `GET /Items/{itemId}` through the identical transport answers the empty `401`, so "no token
    succeeded" is a property of the delivery route rather than of the fixture.
    """
    item_id, _, _ = film(served, DIRECT_PLAY)

    refused = await unauthenticated.get(f"/Items/{item_id}")

    assert refused.status_code == 401
    assert refused.content == b""


# ------------------------------------------------------------------------------------------
# The refusals
# ------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "route",
    [
        "/Videos/{id}/stream",
        "/Videos/{id}/stream.mp4",
        "/Audio/{id}/stream",
        "/Audio/{id}/stream.mp3",
    ],
)
async def test_an_unknown_item_is_the_third_error_shape(
    client: httpx.AsyncClient, route: str
) -> None:
    """Measured on all four: `404`, `text/plain` with no charset, and the fixed 25 bytes.

    **Not** the problem-details `404` `GET /Items/{itemId}/PlaybackInfo` answers for the same
    identifier - one feature, one identifier, two bodies, split by which layer refused
    (behaviours section 1.11).
    """
    answered = await client.get(route.format(id=UNKNOWN_ITEM), params={"static": "true"})

    assert answered.status_code == 404
    assert answered.headers["Content-Type"] == "text/plain"
    assert answered.content == CONTROLLER_ERROR_BODY


async def test_the_negotiation_refuses_the_same_identifier_differently(
    client: httpx.AsyncClient,
) -> None:
    """The other half of the pair, asserted here so the two cannot silently converge."""
    answered = await client.get(f"/Items/{UNKNOWN_ITEM}/PlaybackInfo")

    assert answered.status_code == 404
    assert answered.headers["Content-Type"] == "application/json; charset=utf-8"
    assert json.loads(answered.content)["title"] == "Not Found"


@pytest.mark.parametrize("container", ["a b", "a" * 41])
async def test_a_container_outside_the_pattern_is_a_validation_400(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld], container: str
) -> None:
    """Measured, message included: the reference's data annotation names the expression rather
    than quoting what the client sent, and the refusal happens before the item is looked up."""
    item_id, _, _ = film(served, DIRECT_PLAY)

    answered = await client.get(f"/Videos/{item_id}/stream.{container}", params={"static": "true"})

    assert answered.status_code == 400
    body: dict[str, Any] = json.loads(answered.content)
    assert body["errors"] == {
        "container": [
            PATTERN_MESSAGE.format(name="container", pattern=r"^[a-zA-Z0-9\-\._,|]{0,40}$")
        ]
    }


async def test_the_pattern_refusal_comes_before_the_lookup(client: httpx.AsyncClient) -> None:
    """An unknown item asked for through an illegal container answers the `400`, not the `404` -
    measured, and the ordering is what a framework-declared pattern gives for free."""
    answered = await client.get(f"/Videos/{UNKNOWN_ITEM}/stream.a b", params={"static": "true"})

    assert answered.status_code == 400


# ------------------------------------------------------------------------------------------
# AC-28: the two containers, on one item
# ------------------------------------------------------------------------------------------


async def test_ac28_item_container_is_the_list_and_the_source_is_the_single_form(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """AC-28, on the item this task delivers: the item-level `Container` is the demuxer list and
    the media source's is the one resolved name - and the resolved name is what the static URL is
    spelled with."""
    item_id, _, _ = film(served, DIRECT_PLAY)

    answered = await client.get(f"/Items/{item_id}")
    document = answered.json()

    assert document["Container"] == "mov,mp4,m4a,3gp,3g2,mj2"
    assert document["MediaSources"][0]["Container"] == "mp4"


async def test_ac28_the_two_forms_agree_wherever_the_stored_string_is_one_name(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """The mkv entry, where item and source say the same word - which is 008 T2's finding and the
    half of AC-28 a rule that always split would get wrong.

    ffprobe calls this file `matroska,webm`; what the reference stores is a **normalised** string,
    so the item answers `mkv` and so does the source. Asserting only on the mp4 family could not
    have told "the item carries a list" from "the item carries what ffprobe said".
    """
    item_id, _, _ = film(served, REJECTED_CONTAINER)

    document = (await client.get(f"/Items/{item_id}")).json()

    assert document["Container"] == "mkv"
    assert document["MediaSources"][0]["Container"] == "mkv"


# ------------------------------------------------------------------------------------------
# The advertised size and the served body, joined - which nothing did until T14
# ------------------------------------------------------------------------------------------


async def test_ac14_the_size_the_negotiation_advertises_is_the_body_the_route_serves(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """AC-14 across the two routes that state a length, rather than inside each of them.

    `MediaSources[].Size` and the delivery route's `Content-Length` are **two independent stats of
    one file**: the negotiation reads the size beside the inspection it assembles from, and the
    stream route stats the file again when the request arrives. Every golden in this repository
    carries a fixture size, so the two numbers had never been compared with each other - and a
    client reads that field as the byte length of what it is about to fetch and bounds every range
    request it makes with it.

    The last two requests are what makes this more than an equality: the byte the advertised size
    names as the last one really is the last one, and one past it is refused rather than answered
    with a shorter body.
    """
    item_id, payload, size = film(served, DIRECT_PLAY)

    negotiated = await client.get(f"/Items/{item_id}/PlaybackInfo")
    assert negotiated.status_code == 200, negotiated.text
    advertised = negotiated.json()["MediaSources"][0]["Size"]

    answered = await client.get(f"/Videos/{item_id}/stream", params={"static": "true"})

    assert answered.status_code == 200
    assert advertised == size
    assert int(answered.headers["Content-Length"]) == advertised
    assert len(answered.content) == advertised

    last = await client.get(
        f"/Videos/{item_id}/stream",
        params={"static": "true"},
        headers={"Range": f"bytes={advertised - 1}-{advertised - 1}"},
    )
    assert last.status_code == 206
    assert last.content == payload[-1:]

    past = await client.get(
        f"/Videos/{item_id}/stream",
        params={"static": "true"},
        headers={"Range": f"bytes={advertised}-"},
    )
    assert past.status_code == 416
    assert past.headers["Content-Range"] == f"bytes */{advertised}"


async def test_ac14_a_track_advertises_its_own_size_too(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """The same pairing on the audio route, so the film's agreement cannot be a property of one
    container - and on the entry whose size no other test in this file reads."""
    item_id, _, size = film(served, HIGH_RATE_AUDIO)

    negotiated = await client.get(f"/Items/{item_id}/PlaybackInfo")
    answered = await client.get(f"/Audio/{item_id}/stream", params={"static": "true"})

    assert negotiated.json()["MediaSources"][0]["Size"] == size
    assert int(answered.headers["Content-Length"]) == size
