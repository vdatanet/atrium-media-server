# SPDX-License-Identifier: GPL-3.0-or-later
"""L0 — routed: does the path exist, and does it answer a sane status?

Two halves, and the second is the one that does the work.

**Every route this feature owns is registered.** `docs/compatibility/surface.yaml` is the list of
endpoints v1 serves, and the entries marked `feature: "001"` have to be answering.

**No route exists outside that file.** This is the automated half of Principle VI: an endpoint that
appears in the router without appearing in the surface file fails here, whatever good reason it
was added for. Growth of the API surface is a scope decision recorded in the roadmap, not something
that happens because a route was convenient.

Both halves are checked against **two independent views** of what the application serves, because
each view has a blind spot the other covers:

* the OpenAPI document the framework generates, which knows every route it will route and misses
  any registered with `include_in_schema=False`;
* the route table the factory builds from its own list of routers, which is what path matching and
  `Allow` are built from, and which misses a router that was included without being on that list.

A route visible to one and not the other is a failure on its own, asserted below. That pair is the
reason this file does not reach into the framework's internals to enumerate routes: it does not
have to.

The routing behaviour tests at the bottom are L0 too. What counts as "this path" is looser in the
reference than in the framework, and a client that spells a path in a way the reference accepts
must not get a 404 here.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from atrium.compat.routing import RouteTable

pytestmark = pytest.mark.conformance

REPO_ROOT = Path(__file__).resolve().parents[2]
SURFACE_FILE = REPO_ROOT / "docs" / "compatibility" / "surface.yaml"

#: The features these tests police. A feature joins this set **in the change that implements it**,
#: so that no route can ship ahead of the feature that specifies it - and, just as importantly, so
#: that a feature marked `Implemented` whose route is not registered fails here rather than in
#: somebody's client. 004 joined at T15, which is the line this file's own comment promised.
IMPLEMENTED_FEATURES = frozenset({"001", "002", "004"})

#: 005's routes land across seven tasks (T10-T16), and while they do, the exact-set check below
#: carries the ones that have landed - the same device 002 used between its two route tasks.
#: **T17 deletes this set** by putting "005" in `IMPLEMENTED_FEATURES`, which is what finishing
#: a feature looks like in this file. Every entry must also be in surface.yaml, which
#: `test_no_route_exists_outside_the_surface` keeps true.
LANDED_EARLY: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", "/Items"),  # T10
        ("GET", "/Items/{itemId}"),  # T10
        ("GET", "/UserViews"),  # T11
        ("GET", "/Items/Latest"),  # T11
        ("GET", "/Shows/{seriesId}/Seasons"),  # T12
        ("GET", "/Shows/{seriesId}/Episodes"),  # T12
    }
)


def _load_surface_parser() -> Any:
    """Reuse the parser the surface validator already has, rather than write a second one.

    `tools/` is a directory of standalone programs, not an importable package - deliberately, so
    the probes keep working before any environment exists. Loading the module by path is the price
    of that, and it is cheaper than two parsers disagreeing about the same file.
    """
    path = REPO_ROOT / "tools" / "extract_v1_surface.py"
    spec = importlib.util.spec_from_file_location("atrium_surface_tool", path)
    assert spec is not None and spec.loader is not None, f"cannot load {path}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def surface_endpoints() -> list[dict[str, str]]:
    parser = _load_surface_parser()
    _reference, endpoints = parser.parse_surface(SURFACE_FILE.read_text(encoding="utf-8"))
    assert endpoints, f"{SURFACE_FILE} parsed to nothing; the parser and the file disagree"
    return list(endpoints)


def surface_paths(features: frozenset[str] | None = None) -> frozenset[tuple[str, str]]:
    """`(method, path)` for the whole file, or only for the features named."""
    return frozenset(
        (entry["method"], entry["path"])
        for entry in surface_endpoints()
        if features is None or entry.get("feature") in features
    )


def documented_paths(app: FastAPI) -> frozenset[tuple[str, str]]:
    """What the framework will route, read from the document it generates for itself."""
    document = app.openapi()
    return frozenset(
        (method.upper(), path)
        for path, operations in document.get("paths", {}).items()
        for method in operations
    )


def tabled_paths(app: FastAPI) -> frozenset[tuple[str, str]]:
    """What the factory's own route table says it serves."""
    table: RouteTable = app.state.routes
    return table.paths()


# --------------------------------------------------------------------------------------------
# Registration
# --------------------------------------------------------------------------------------------


def test_every_route_this_feature_owns_is_registered(app: FastAPI) -> None:
    expected = surface_paths(IMPLEMENTED_FEATURES)
    assert expected, "no 001 entries in the surface file; the parser or the file changed shape"
    missing = expected - documented_paths(app)
    assert not missing, f"in surface.yaml and not served: {sorted(missing)}"


def test_no_route_exists_outside_the_surface(app: FastAPI) -> None:
    """Principle VI, enforced rather than remembered."""
    extra = documented_paths(app) - surface_paths()
    assert not extra, (
        f"served and not in {SURFACE_FILE.name}: {sorted(extra)}. An endpoint reaches the surface "
        f"file with a named consumer and a conformance level, or it does not reach the router."
    )


def test_no_route_ships_ahead_of_its_feature(app: FastAPI) -> None:
    """Everything served belongs to a feature that has been implemented.

    A 003 route registered while 003 is unimplemented is in the surface file, so the check above
    would pass it. This one fails until `IMPLEMENTED_FEATURES` names the feature - a line that gets
    changed on purpose, in the change that finishes it.

    002 arrived across two tasks, and for the two changes between them this set was accompanied by
    an explicit list of the individual routes that had landed. That list is gone now, which is what
    finishing a feature looks like here - and `LANDED_EARLY` is 005 doing the same thing across
    seven tasks.
    """
    assert documented_paths(app) == surface_paths(IMPLEMENTED_FEATURES) | LANDED_EARLY


def test_an_unlisted_route_fails_the_check(app: FastAPI) -> None:
    """The check has to be able to fail, and this is the failure it exists for."""

    @app.get("/System/NotInTheSurfaceFile")
    def _unlisted() -> dict[str, str]:  # pragma: no cover - never called
        return {}

    app.openapi_schema = None  # the document is cached; this route arrived after the first build
    extra = documented_paths(app) - surface_paths()
    assert extra == {("GET", "/System/NotInTheSurfaceFile")}


def test_a_literal_path_wins_over_the_parameterised_one(app: FastAPI) -> None:
    """`/users/public` is the public route, not a user whose identifier is `public`.

    The table tries literals first and then patterns **in registration order**, so this is a
    property of the order the routers are declared in - which makes it worth a test rather than a
    comment asking the next person to keep it.
    """
    table: RouteTable = app.state.routes
    assert table.canonicalise("/users/public") == "/Users/Public"
    assert table.canonicalise("/USERS/ME") == "/Users/Me"
    assert table.canonicalise("/users/configuration") == "/Users/Configuration"
    assert table.canonicalise("/Users/abc123") == "/Users/abc123"


def test_the_two_views_of_the_routes_agree(app: FastAPI) -> None:
    """A route in the router but not the table, or the reverse, is a wiring bug either way.

    The table is built from `server.ROUTERS`; the document is built from what was included. They
    diverge when a router is included without being listed, or when a route is registered with
    `include_in_schema=False` - and each of those makes one of the two checks above blind.
    """
    assert documented_paths(app) == tabled_paths(app)


def test_the_surface_file_and_the_specification_agree_on_001(app: FastAPI) -> None:
    """The four endpoints 001 specifies, named here so a silent removal is not silent."""
    assert surface_paths(frozenset({"001"})) == {
        ("GET", "/System/Info/Public"),
        ("GET", "/System/Info"),
        ("GET", "/System/Ping"),
        ("POST", "/System/Ping"),
    }


def test_the_surface_file_and_the_specification_agree_on_002(app: FastAPI) -> None:
    """The seven endpoints 002 specifies. Named one by one for the same reason as 001's."""
    assert surface_paths(frozenset({"002"})) == {
        ("POST", "/Users/AuthenticateByName"),
        ("GET", "/Users/Public"),
        ("GET", "/Users/Me"),
        ("GET", "/Users/{userId}"),
        ("POST", "/Users/Configuration"),
        ("GET", "/Sessions"),
        ("POST", "/Sessions/Capabilities/Full"),
    }


# --------------------------------------------------------------------------------------------
# What counts as "this path"
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "spelling",
    [
        "/System/Info/Public",
        "/system/info/public",
        "/SYSTEM/INFO/PUBLIC",
        "/System/info/Public",
        "/System/Info/Public/",
    ],
)
async def test_the_reference_spellings_all_reach_the_route(
    client: httpx.AsyncClient, spelling: str
) -> None:
    """Case-insensitive, and one trailing slash.

    [probe: tools/probe_routing.py, Jellyfin 10.11.11, 2026-08-26]. A client that lowercases its
    paths is served by the reference; before this was measured it got a 404 here.
    """
    response = await client.get(spelling)
    assert response.status_code == 200
    canonical = await client.get("/System/Info/Public")
    assert response.content == canonical.content


async def test_two_trailing_slashes_are_not_one(client: httpx.AsyncClient) -> None:
    """The reference draws the line here, and so does Atrium.

    Starlette's own answer was a `307` to the working URL, which is worse than either behaviour:
    it invents a redirect the reference does not send, to a path the reference refuses.
    """
    response = await client.get("/System/Info/Public//")
    assert response.status_code == 404
    assert response.content == b""


async def test_a_lowercased_post_route_is_also_matched(client: httpx.AsyncClient) -> None:
    assert (await client.post("/system/ping")).status_code == 200


# --------------------------------------------------------------------------------------------
# How it refuses
# --------------------------------------------------------------------------------------------


async def test_an_unknown_path_is_an_empty_404(client: httpx.AsyncClient) -> None:
    """behaviours 1.11's first shape, which until now was documented rather than implemented.

    FastAPI's default is `{"detail": "Not Found"}` - the shape that document explicitly says is
    neither of the reference's two.
    """
    response = await client.get("/System/ThisRouteDoesNotExist")
    assert response.status_code == 404
    assert response.content == b""
    assert "content-type" not in response.headers


@pytest.mark.parametrize("method", ["put", "delete", "patch"])
async def test_a_method_the_path_does_not_have_is_an_empty_405(
    client: httpx.AsyncClient, method: str
) -> None:
    response = await getattr(client, method)("/System/Ping")
    assert response.status_code == 405
    assert response.content == b""
    assert "content-type" not in response.headers


async def test_allow_lists_every_method_the_path_has(client: httpx.AsyncClient) -> None:
    """Two routes, one path, and the header has to know about both.

    Starlette fills `Allow` from the first route whose path matched, which for `/System/Ping`
    advertised `POST` alone - the reference sends `GET, POST`.
    [probe: tools/probe_routing.py, Jellyfin 10.11.11, 2026-08-26]
    """
    response = await client.put("/System/Ping")
    assert response.headers["allow"] == "GET, POST"

    single = await client.put("/System/Info/Public")
    assert single.headers["allow"] == "GET"


@pytest.mark.parametrize(
    ("method", "path"), [("get", "/System/ThisRouteDoesNotExist"), ("put", "/System/Ping")]
)
async def test_a_refusal_is_empty_but_not_bare(
    client: httpx.AsyncClient, method: str, path: str
) -> None:
    """Empty body, and still every header the reference puts on one.

    The reference answers both of these with `Content-Length: 0`, `Server` and
    `X-Response-Time-ms`. [probe: manual requests, Jellyfin 10.11.11, 2026-08-26]
    Here that is a property of middleware order rather than of the handler: the header middleware
    is outermost, so it wraps refusals decided before any route ran.
    """
    response = await getattr(client, method)(path)
    assert response.content == b""
    assert response.headers["content-length"] == "0"
    assert response.headers["server"].startswith("Atrium/")
    assert "x-response-time-ms" in response.headers


@pytest.mark.parametrize("method", ["head", "options"])
async def test_head_and_options_are_not_free(client: httpx.AsyncClient, method: str) -> None:
    """Neither is automatically anything, in the reference or here.

    A framework that answered `HEAD` from the `GET` handler, or `OPTIONS` with an `Allow`-bearing
    `200`, would be a difference on every route at once.
    """
    response = await getattr(client, method)("/System/Info/Public")
    assert response.status_code == 405
    assert response.headers["allow"] == "GET"


# --------------------------------------------------------------------------------------------
# The table itself
# --------------------------------------------------------------------------------------------


def test_the_table_canonicalises_rather_than_lowercases(app: FastAPI) -> None:
    """What the middleware hands the router is the route's own spelling."""
    table: RouteTable = app.state.routes
    assert table.canonicalise("/system/info/public") == "/System/Info/Public"
    assert table.canonicalise("/System/Info/Public/") == "/System/Info/Public"
    assert table.canonicalise("/System/Info/Public//") is None
    assert table.canonicalise("/nothing/here") is None


def test_the_table_keeps_a_parameter_exactly_as_it_arrived() -> None:
    """Only the literal segments are respelled - a parameter is data, not a path.

    001 has no parameterised route, and 002's `/Users/{userId}` is the first. Getting this wrong
    would lowercase an identifier, which is invisible until something case-sensitive reads one.
    """
    from fastapi import APIRouter

    router = APIRouter()

    @router.get("/Users/{userId}/Items")
    def _items(userId: str) -> dict[str, str]:  # noqa: N803 - the reference's spelling
        return {}  # pragma: no cover - never called

    table = RouteTable.from_routers([router])
    assert table.canonicalise("/users/AbCdEf/items") == "/Users/AbCdEf/Items"
    assert table.canonicalise("/USERS/AbCdEf/ITEMS/") == "/Users/AbCdEf/Items"
    assert table.methods_for("/users/AbCdEf/items") == {"GET"}
