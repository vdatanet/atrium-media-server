# SPDX-License-Identifier: GPL-3.0-or-later
"""`415` where a body's media type is one this server cannot read — behaviours §1.11's fifth shape.

**This closes an accepted gap, and the gap's own description was wrong about the request.** From
2026-09-01 behaviours §5 carried *"a required body that is missing entirely is `400` and not
`415`"*, listing five routes whose body it called required. Measured against a reference instance,
one request per case `[probe: tools/probe_content_type_gate.py, Jellyfin 10.11.11, 2026-09-06]`:

```
                                no body, no CT   body, no CT   body, text/plain   valid body
POST /Sessions/Playing                     415           415                415          204
POST /Sessions/Playing/Progress            415           415                415          204
POST /Sessions/Playing/Stopped             415           415                415          204
POST /Items/{itemId}/PlaybackInfo          200           415                415          200
```

So the gate is not about a **missing body**: it is about the media type of a body the server has to
read. A required body must be read however the request arrived; an optional one is read only when
something was sent. `PlaybackInfo` is in the second group, which is why that list of five was four.

The two rows of that table are the two tests below, and neither passes under the other's rule.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from atrium.api.deps import require_user
from atrium.compat.content_type import readable
from atrium.compat.errors import (
    PROBLEM_TYPE_UNSUPPORTED_MEDIA_TYPE,
    UNSUPPORTED_MEDIA_TYPE_TITLE,
)
from atrium.config.paths import DataPaths
from atrium.server import create_app
from tests.conftest import data_dir
from tests.fixtures.query import QueryWorld, build_query_world

#: A route whose body is **required**: 007's reporting routes, measured as `415` even with no body.
REQUIRED_BODY = "/Sessions/Playing"

#: A route whose body is **optional**: measured as `200` with no body and `415` with an unreadable
#: one, which is the distinction the gap row missed.
OPTIONAL_BODY = "/Items/{}/PlaybackInfo"


@dataclass(frozen=True)
class Harness:
    app: FastAPI
    world: QueryWorld


@pytest.fixture
def harness(tmp_path: Path) -> Iterator[Harness]:
    paths: DataPaths = data_dir(tmp_path / "atrium")
    built = create_app(paths)
    built.state.readiness.mark_ready()
    with built.state.sessions.begin() as opened:
        world = build_query_world(opened)
    yield Harness(app=built, world=world)
    built.dependency_overrides.clear()
    built.state.db.dispose()


@pytest.fixture
def app(harness: Harness) -> FastAPI:
    harness.app.dependency_overrides[require_user] = lambda: harness.world.everyone
    return harness.app


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://atrium:8096") as opened:
        yield opened


async def post(
    client: httpx.AsyncClient, path: str, body: bytes | None, content_type: str | None
) -> httpx.Response:
    headers = {} if content_type is None else {"Content-Type": content_type}
    return await client.request("POST", path, content=body, headers=headers)


# ------------------------------------------------------------------------------------------
# The two rows of the measured table
# ------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "body", "content_type"),
    [
        ("no body and no content type", None, None),
        ("a body and no content type", b'{"ItemId":"x"}', None),
        ("a body announced as text", b'{"ItemId":"x"}', "text/plain"),
        ("a body announced as a form", b"ItemId=x", "application/x-www-form-urlencoded"),
        ("a body announced as anything", b'{"ItemId":"x"}', "*/*"),
    ],
    ids=lambda one: one if isinstance(one, str) else "",
)
async def test_a_required_body_refuses_every_unreadable_media_type(
    client: httpx.AsyncClient, label: str, body: bytes | None, content_type: str | None
) -> None:
    """Including **no body at all**, which is the case that separates this route from the next.

    A route that must read a body refuses a request it could not read one from, whether or not one
    was sent — measured on all three of 007's reporting routes.
    """
    answered = await post(client, REQUIRED_BODY, body, content_type)

    assert answered.status_code == 415, f"{label}: {answered.text[:160]}"


async def test_an_optional_body_is_only_refused_when_one_arrives(
    client: httpx.AsyncClient, harness: Harness
) -> None:
    """The row the gap's description got wrong: no body is **not** an unreadable body.

    `PlaybackInfo` reads a body when one is sent and answers with defaults when none is. So a
    request carrying nothing is served, and the very same request carrying a body it cannot read is
    refused — one route, two answers, decided by whether there is anything to read.
    """
    path = OPTIONAL_BODY.format(harness.world.corpus[0])

    served = await post(client, path, None, None)
    assert served.status_code == 200, served.text[:160]

    refused = await post(client, path, b'{"UserId":"x"}', "text/plain")
    assert refused.status_code == 415


# ------------------------------------------------------------------------------------------
# The shape, and what counts as readable
# ------------------------------------------------------------------------------------------


async def test_the_refusal_is_the_problem_details_shape(client: httpx.AsyncClient) -> None:
    """The fifth error shape, keyed and typed like the other four (behaviours §1.11).

    No `errors` map — there was no validation to report, which is the whole point of refusing
    ahead of the binding.
    """
    answered = await post(client, REQUIRED_BODY, None, None)
    body = json.loads(answered.text)

    assert list(body) == ["type", "title", "status", "traceId"]
    assert body["type"] == PROBLEM_TYPE_UNSUPPORTED_MEDIA_TYPE
    assert body["title"] == UNSUPPORTED_MEDIA_TYPE_TITLE
    assert body["status"] == 415
    assert body["traceId"]


@pytest.mark.parametrize(
    ("content_type", "accepted"),
    [
        ("application/json", True),
        ("application/json; charset=utf-8", True),
        ("APPLICATION/JSON", True),
        ("text/json", True),
        ("application/problem+json", True),
        ("application/vnd.api+json", True),
        ("application/x-www-form-urlencoded", False),
        ("*/*", False),
        ("", False),
        (None, False),
    ],
)
def test_what_counts_as_readable_is_a_suffix_rule(content_type: str | None, accepted: bool) -> None:
    """All nine spellings measured on one route, and the tenth is the absent header.

    A suffix rule rather than a list, which is what an input formatter does: anything ending
    `+json` is read, so `application/problem+json` and `application/vnd.api+json` both are.
    """
    assert readable(content_type) is accepted


async def test_a_get_is_never_gated(client: httpx.AsyncClient, harness: Harness) -> None:
    """The gate reads a request's media type and must not invent a reason to refuse a read.

    A `GET` carries no body and declares no type, and every listing in this project would answer
    `415` if the rule were applied by header alone rather than by whether a body must be read.
    """
    answered = await client.get("/Items", params={"recursive": "true", "limit": "1"})

    assert answered.status_code == 200
