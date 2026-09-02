# SPDX-License-Identifier: GPL-3.0-or-later
"""The three framework fights, and the fourth one found while settling them.

Feature 005's routes do not exist yet, so these build a throwaway application declaring the
parameters a real route will declare. That is the point rather than a workaround: the machinery
under test is route-agnostic on purpose, and a test that could only run against `/Items` would be
testing `/Items`.

Each fight is a place where the framework's default is **silently** wrong. `StartIndex` against a
route declaring `startIndex` is not rejected, it is ignored - so every page is page one, and the
symptom is a client that never scrolls rather than a test that fails.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from enum import StrEnum
from pathlib import Path

import httpx
import pytest
from fastapi import APIRouter, FastAPI, Query

from atrium.compat.errors import (
    EXCEPTION_HANDLERS,
    NOT_FOUND_TITLE,
    PROBLEM_TYPE_BAD_REQUEST,
    PROBLEM_TYPE_NOT_FOUND,
    VALIDATION_TITLE,
    NotFoundError,
    trace_id,
)
from atrium.compat.query_params import (
    GLOBAL_PARAMETERS,
    UNKNOWN_CLIENT,
    AmbiguousParameterError,
    CanonicalQueryMiddleware,
    IgnoredParameters,
    QueryParameterTable,
    known_tokens,
)
from atrium.compat.responses import AtriumJSONResponse
from atrium.compat.routing import RelaxedPathMiddleware, RouteTable
from atrium.config.paths import IGNORED_PARAMETERS_FILE
from tests.conftest import data_dir


class Colour(StrEnum):
    RED = "Red"
    BLUE = "Blue"


def build_router() -> APIRouter:
    """One route, three parameters, spelled the way the pinned document spells them."""
    router = APIRouter()

    @router.get("/Items")
    async def items(  # pyright: ignore[reportUnusedFunction]
        startIndex: int = Query(0),  # noqa: N803 - the wire spelling is the contract
        limit: int | None = Query(None),
        searchTerm: str | None = Query(None),  # noqa: N803
    ) -> dict[str, object]:
        return {"startIndex": startIndex, "limit": limit, "searchTerm": searchTerm}

    @router.get("/Items/{itemId}")
    async def item(itemId: str) -> dict[str, str]:  # noqa: N803  # pyright: ignore
        if itemId != "known":
            raise NotFoundError
        return {"Id": itemId}

    return router


@pytest.fixture
def recorder() -> IgnoredParameters:
    return IgnoredParameters()


@pytest.fixture
def app(recorder: IgnoredParameters) -> FastAPI:
    router = build_router()
    routes = RouteTable.from_routers([router])
    table = QueryParameterTable.from_routers([router])
    built = FastAPI(
        default_response_class=AtriumJSONResponse, exception_handlers=dict(EXCEPTION_HANDLERS)
    )
    built.add_middleware(CanonicalQueryMiddleware, table=table, routes=routes, ignored=recorder)
    built.add_middleware(RelaxedPathMiddleware, table=routes)
    built.include_router(router)
    built.router.redirect_slashes = False
    built.state.routes = routes
    return built


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://atrium:8096") as opened:
        yield opened


# ------------------------------------------------------------------------------------------
# Fight 1: parameter names match case-insensitively (behaviours 1.15)
# ------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "spelling",
    ["startIndex", "StartIndex", "startindex", "STARTINDEX", "sTaRtInDeX"],
)
async def test_every_casing_of_a_parameter_binds(client: httpx.AsyncClient, spelling: str) -> None:
    answer = await client.get("/Items", params={spelling: 7})
    assert answer.json()["startIndex"] == 7, (
        f"{spelling} did not bind. The framework's default here is not a refusal, it is silence: "
        f"the parameter is ignored and every page is page one."
    )


async def test_a_whole_request_of_mangled_spellings_binds(client: httpx.AsyncClient) -> None:
    answer = await client.get(
        "/Items", params={"STARTINDEX": 3, "Limit": 5, "searchterm": "a thing"}
    )
    assert answer.json() == {"startIndex": 3, "limit": 5, "searchTerm": "a thing"}


async def test_a_value_is_never_touched(client: httpx.AsyncClient) -> None:
    """Only the key is rewritten. `+`, `;` and an over-escaped octet all mean something inside a
    search term and nothing inside a parameter name."""
    answer = await client.get("/Items", params={"SEARCHTERM": "a+b;c d%2Fe"})
    assert answer.json()["searchTerm"] == "a+b;c d%2Fe"


# ------------------------------------------------------------------------------------------
# The startup check (plan section 9 row 5)
# ------------------------------------------------------------------------------------------


def test_the_table_covers_every_route_of_the_real_application() -> None:
    """The mitigation for "a route added later is missed": the walk is over the same ROUTERS the
    application includes, so a new route is in the table by construction. Asserted rather than
    assumed, because "by construction" is a claim about code that can change."""
    from atrium.server import ROUTERS

    table = QueryParameterTable.from_routers(ROUTERS)
    routes = RouteTable.from_routers(ROUTERS)
    templates = {template for _method, template in routes.paths()}
    assert templates <= set(table.by_template)


def test_every_route_accepts_the_authentication_parameters() -> None:
    """`compat.auth` reads the token straight off the query string - it belongs to no route's
    signature. Without this the recorder would report `api_key` as an ignored parameter on every
    request a media player makes, because media players cannot set headers (002 section 3.1)."""
    from atrium.server import ROUTERS

    table = QueryParameterTable.from_routers(ROUTERS)
    for template, spellings in table.by_template.items():
        for name in GLOBAL_PARAMETERS:
            assert table.canonical(template, name.upper()) == name, (
                f"{template} would record {name} as ignored"
            )
            assert name.lower() in spellings


def test_two_parameters_differing_only_in_case_fail_at_boot() -> None:
    """Not at request time, and not by picking one. Canonicalisation could not say which one an
    incoming `limit` meant, and either choice binds the wrong parameter for some client."""
    router = APIRouter()

    @router.get("/Broken")
    async def broken(  # pyright: ignore[reportUnusedFunction]
        limit: int = Query(0),
        Limit: int = Query(0),  # noqa: N803
    ) -> dict[str, int]:
        return {"limit": limit, "Limit": Limit}

    with pytest.raises(AmbiguousParameterError, match="differ only"):
        QueryParameterTable.from_routers([router])


# ------------------------------------------------------------------------------------------
# Fight 2: the ignored-parameter recorder (spec section 3.3, AC-15)
# ------------------------------------------------------------------------------------------


async def test_an_unmatched_key_lands_in_the_recorder(
    client: httpx.AsyncClient, recorder: IgnoredParameters
) -> None:
    answer = await client.get("/Items", params={"limit": 2, "is3D": "true"})
    assert answer.status_code == 200, "a Tier 3 parameter is ignored, never rejected"
    assert recorder.counts == {("/Items", "is3D", ""): 1}


async def test_the_recorder_counts_rather_than_deduplicates(
    client: httpx.AsyncClient, recorder: IgnoredParameters
) -> None:
    for _ in range(3):
        await client.get("/Items", params={"is3D": "true"})
    assert recorder.counts[("/Items", "is3D", "")] == 3
    assert recorder.total() == 3


async def test_the_recorder_keys_on_the_route_template_not_the_path(
    client: httpx.AsyncClient, recorder: IgnoredParameters
) -> None:
    """`/Items/known` and `/Items/other` are one route. Counting per concrete path would produce
    a tally as long as the library rather than as long as the parameter set."""
    await client.get("/Items/known", params={"madeUp": 1})
    await client.get("/Items/other", params={"madeUp": 1})
    assert recorder.counts == {("/Items/{itemId}", "madeUp", ""): 2}


async def test_a_request_matching_no_route_records_nothing(
    client: httpx.AsyncClient, recorder: IgnoredParameters
) -> None:
    """It is on its way to an empty 404. Recording would count parameters against a route that
    does not exist, and the tally exists to say what real clients send to real endpoints."""
    await client.get("/NotARoute", params={"madeUp": 1})
    assert recorder.counts == {}


def test_each_distinct_pair_is_logged_once(
    recorder: IgnoredParameters, caplog: pytest.LogCaptureFixture
) -> None:
    """A client that sends an unimplemented parameter sends it on every request. The useful
    signal is the set, not the volume - and the volume is in `counts` either way."""
    with caplog.at_level("INFO", logger="atrium.compat.query_params"):
        for _ in range(5):
            recorder.record("/Items", "is3D")
        recorder.record("/Items", "isHD")
    assert len(caplog.records) == 2
    assert recorder.counts[("/Items", "is3D", "")] == 5


async def test_the_tally_names_the_client_that_sent_the_parameter(
    client: httpx.AsyncClient, recorder: IgnoredParameters
) -> None:
    """AC-10's fourth column, and the one 010 plan section 6.8 found missing.

    Three of the four columns were already here. The client was not, although every request that
    carries a client-identification header carries it - and without it the tally cannot be acted
    on: promoting a parameter to Tier 2 or declining it in writing is a decision about **whose**
    client would notice, and a count with no name answers a different question.
    """
    await client.get(
        "/Items",
        params={"is3D": "true"},
        headers={"X-Emby-Authorization": 'MediaBrowser Client="Embeat", DeviceId="d", Version="1"'},
    )
    await client.get(
        "/Items",
        params={"is3D": "true"},
        headers={"Authorization": 'MediaBrowser Client="Atrium tvOS", DeviceId="e", Version="2"'},
    )
    await client.get("/Items", params={"is3D": "true"})
    assert recorder.counts == {
        ("/Items", "is3D", "Embeat"): 1,
        ("/Items", "is3D", "Atrium tvOS"): 1,
        ("/Items", "is3D", ""): 1,
    }, "one parameter, one endpoint, three callers - and the tally must be able to tell them apart"
    assert [row["client"] for row in recorder.rows()] == [
        UNKNOWN_CLIENT,
        "Atrium tvOS",
        "Embeat",
    ], "a caller that named itself is a row of its own, and one that did not is not a blank cell"


async def test_a_dropped_token_carries_the_client_too(
    client: httpx.AsyncClient, recorder: IgnoredParameters
) -> None:
    """The other half of the recorder, and the half a middleware cannot reach.

    An unrecognised enum token is dropped inside a route's own parser (behaviours section 1.12),
    three frames above the headers. The route hands its parsers a recorder that already knows who
    is asking, which is why `known_tokens` takes a `Recorder` and not the tally itself - a parser
    has no business knowing that a client exists.
    """
    bound = recorder.for_client("Embeat")
    known_tokens(["Nonsense"], Colour, route="/Items", parameter="colour", ignored=bound)
    assert recorder.counts == {("/Items", "colour=Nonsense", "Embeat"): 1}


async def test_the_tally_is_written_to_the_data_directory_at_shutdown_and_to_no_route(
    tmp_path: Path,
) -> None:
    """D-5's shape, both halves, and the second one is a principle rather than a preference.

    **A file in the data directory**, written in the lifespan's `finally` because that is the one
    moment the tally is complete - it is after the last request a route could have answered.
    **And never a route**: an endpoint serving it would be an endpoint Jellyfin does not have,
    which is Principle I's first forbidden line, and "optional, behind a flag" does not save it
    because an extension a client can discover is still a delta.
    """
    from atrium.server import ROUTERS, create_app

    paths = data_dir(tmp_path / "atrium")
    built = create_app(paths)
    assert not paths.ignored_parameters.exists(), "nothing is written before the process stops"
    async with built.router.lifespan_context(built):
        built.state.ignored_parameters.record("/Items", "is3D", "Embeat")
        assert not paths.ignored_parameters.exists(), (
            "a tally written while the server is still answering is a tally that is not complete"
        )

    written = json.loads(paths.ignored_parameters.read_text(encoding="utf-8"))
    assert written["total"] == 1
    assert written["rows"] == [
        {"parameter": "is3D", "endpoint": "/Items", "count": 1, "client": "Embeat"}
    ], "AC-10 names four columns: parameter, endpoint, count and client"

    templates = {template for _method, template in RouteTable.from_routers(ROUTERS).paths()}
    serving = [
        template
        for template in templates
        if "ignored" in template.lower() or "parameter" in template.lower()
    ]
    assert not serving, (
        f"{serving} would serve this server's own diagnostics over HTTP. Jellyfin has no such "
        f"endpoint, so it is a delta a client can discover (Principle I) - and the tally is a "
        f"file for exactly that reason"
    )
    assert IGNORED_PARAMETERS_FILE not in str(templates)


# ------------------------------------------------------------------------------------------
# Fight 3: an unrecognised enum token is dropped (behaviours 1.12)
# ------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("sent", "kept", "dropped"),
    [
        (["Red"], [Colour.RED], []),
        (["Red", "Blue"], [Colour.RED, Colour.BLUE], []),
        (["Blue", "Red"], [Colour.BLUE, Colour.RED], []),
        (["Red", "Nonsense"], [Colour.RED], ["Nonsense"]),
        (["Nonsense"], [], ["Nonsense"]),
        (["red", "BLUE"], [Colour.RED, Colour.BLUE], []),
        ([" Red "], [Colour.RED], []),
        ([""], [], []),
        ([], [], []),
    ],
    ids=[
        "one known",
        "two known",
        "order is the client's",
        "one known one not",
        "only unknown",
        "case-insensitive values",
        "surrounding space",
        "empty token records nothing",
        "nothing at all",
    ],
)
def test_the_enum_helper_keeps_drops_and_records(
    sent: list[str], kept: list[Colour], dropped: list[str], recorder: IgnoredParameters
) -> None:
    result = known_tokens(sent, Colour, route="/Items", parameter="colour", ignored=recorder)
    assert list(result) == kept
    assert [key[1].split("=", 1)[1] for key in recorder.counts] == dropped


def test_an_unknown_token_does_not_take_the_known_ones_with_it() -> None:
    """`sortBy=SortName,Nonsense` keeps `SortName`. Dropping the whole parameter would be a
    different behaviour that happens to pass a test asserting only that it did not raise."""
    assert known_tokens(["Red", "Nonsense", "Blue"], Colour) == (Colour.RED, Colour.BLUE)


# ------------------------------------------------------------------------------------------
# The validation 400 (behaviours 1.11)
# ------------------------------------------------------------------------------------------


async def test_an_unparseable_value_is_a_400_not_a_422(client: httpx.AsyncClient) -> None:
    answer = await client.get("/Items", params={"limit": "abc"})
    assert answer.status_code == 400, "FastAPI's own answer is 422, which is not a shape the "
    "reference has"


async def test_the_validation_body_is_problem_details(client: httpx.AsyncClient) -> None:
    """Asserted on the body, not the status. behaviours §1.11's whole point is that the same
    status carries different bytes depending on which layer refused."""
    answer = await client.get("/Items", params={"limit": "abc"})
    body = answer.json()
    assert body["type"] == PROBLEM_TYPE_BAD_REQUEST
    assert body["title"] == VALIDATION_TITLE
    assert body["status"] == 400
    assert body["errors"] == {"limit": ["The value 'abc' is not valid."]}
    assert body["traceId"].startswith("00-")


async def test_the_errors_key_is_the_declared_spelling(client: httpx.AsyncClient) -> None:
    """Measured: a request sending `Limit=abc` against a route declaring `limit` comes back keyed
    `limit`. Canonicalisation is what produces that, so this is the two fights meeting."""
    answer = await client.get("/Items", params={"LIMIT": "abc"})
    assert list(answer.json()["errors"]) == ["limit"]


async def test_the_validation_response_is_json_with_a_charset(client: httpx.AsyncClient) -> None:
    """`application/json; charset=utf-8`, measured - **not** `application/problem+json`, which is
    what the natural implementation sends and what the framework would default to."""
    answer = await client.get("/Items", params={"limit": "abc"})
    assert answer.headers["content-type"].startswith("application/json")
    assert "charset=utf-8" in answer.headers["content-type"]


async def test_a_handler_not_found_is_problem_details_too(client: httpx.AsyncClient) -> None:
    answer = await client.get("/Items/missing")
    assert answer.status_code == 404
    body = answer.json()
    assert body == {
        "type": PROBLEM_TYPE_NOT_FOUND,
        "title": NOT_FOUND_TITLE,
        "status": 404,
        "traceId": body["traceId"],
    }


async def test_an_unmatched_path_is_still_the_empty_404(client: httpx.AsyncClient) -> None:
    """The two `404`s are different bytes, decided by which layer refused. A problem-details
    handler that swallowed the routing refusal would undo 001 T17."""
    answer = await client.get("/NotARoute")
    assert answer.status_code == 404
    assert answer.content == b""


def test_a_trace_id_has_the_w3c_shape() -> None:
    parts = trace_id().split("-")
    assert parts[0] == "00"
    assert len(parts[1]) == 32
    assert len(parts[2]) == 16
    assert parts[3] == "00"
    assert trace_id() != trace_id(), "per request by definition"
