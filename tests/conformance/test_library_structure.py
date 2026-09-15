# SPDX-License-Identifier: GPL-3.0-or-later
"""`/Library/VirtualFolders` and `/Library/Refresh` at the boundary a client sees: 014 AC-6, AC-7.

Every request names its address through `test_setup_window.ask`, and unless it says otherwise it is
**from this machine, during setup, with no token** - the caller the window admits with nothing to
sign in with, and the one `atrium-admin library add` is. What the window admits and refuses is that
module's subject; this one is what the routes then do.

**Nothing here asks for a scan unless it says so**, and the three that do swap the server's scanner
for one handed the prober the 003 fixture tree's dummy bytes deserve (`tests/conftest.py`'s
`not_media`), so a scan costs no process launch per file.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from atrium import server as atrium_server
from atrium.compat.errors import (
    CONTROLLER_ERROR_BODY,
    PROBLEM_TYPE_BAD_REQUEST,
    VALIDATION_TITLE,
)
from atrium.config.paths import DataPaths
from atrium.db.repositories import LibraryRepository
from atrium.library.scanner import Scanner
from atrium.users.first_account import FIRST_ACCOUNT_NAME
from tests.conformance.test_setup_window import (
    ELSEWHERE,
    LOOPBACK,
    PASSWORD,
    ask,
    finish_setup,
    make_account,
    token_for,
)
from tests.conftest import not_media
from tests.fixtures.library import BuiltFixture
from tests.library.test_scanner import PATIENCE, Gate, wrap_scan

pytestmark = pytest.mark.conformance

FOLDERS = "/Library/VirtualFolders"
REFRESH = "/Library/Refresh"
JSON_TYPE = "application/json; charset=utf-8"

#: Spec section 3.6.1's table, as `(collectionType sent, listed, on the view)`: the three types
#: this server scans, the five it stores and does not scan, an omitted type, and `photos`, which
#: the reference does not declare and stores with no type. `mixed` is a type of the listing and
#: not of the view `[probe: tools/probe_first_time_setup.py, Jellyfin 10.11.11, 2026-09-14]`.
TYPE_TABLE = (
    ("movies", "movies", "movies"),
    ("tvshows", "tvshows", "tvshows"),
    ("music", "music", "music"),
    ("musicvideos", "musicvideos", "musicvideos"),
    ("homevideos", "homevideos", "homevideos"),
    ("boxsets", "boxsets", "boxsets"),
    ("books", "books", "books"),
    ("mixed", "mixed", None),
    (None, None, None),
    ("photos", None, None),
)


@pytest.fixture
async def server(paths: DataPaths) -> AsyncIterator[FastAPI]:
    """A server nobody has set up, with its scanner stopped afterwards - an admitted refresh
    starts one.

    **Built through `atrium.server.create_app` looked up when the fixture runs**, and not through
    the shared `app` fixture: `tests/conftest.py` records the suite's requests for the L2 coverage
    check by replacing that attribute in `pytest_configure`, after `conftest.py` had already bound
    the original name - so a request to the shared `app` reached no recorder, and with every one of
    this module's listings sent there, T7's whole-suite run failed on `GET /Library/VirtualFolders`
    *"asked by no test"* (014 T7, 2026-09-14). The shared fixture has looked the attribute up too
    since 2026-09-15; this one stays its own for the scanner it stops.
    """
    app = atrium_server.create_app(paths)
    app.state.readiness.mark_ready()
    yield app
    await app.state.scanner.stop()


@pytest.fixture
def shelf(tmp_path: Path) -> Path:
    """Directories that exist, for libraries that are only listed."""
    root = tmp_path / "shelf"
    for name in ("films", "shows", "outer/inner", "body", "elsewhere"):
        (root / name).mkdir(parents=True)
    (root / "a file.txt").write_text("not a directory", encoding="utf-8")
    return root


async def add(
    app: FastAPI,
    *,
    body: Any = None,
    peer: str = LOOPBACK,
    token: str | None = None,
    **params: str,
) -> httpx.Response:
    return await ask(app, peer, "POST", FOLDERS, token=token, json=body, params=params)


async def listing(app: FastAPI) -> list[dict[str, Any]]:
    answered = await ask(app, LOOPBACK, "GET", FOLDERS)
    assert answered.status_code == 200, answered.content
    assert answered.headers["content-type"] == JSON_TYPE
    rows: list[dict[str, Any]] = answered.json()
    return rows


async def row_named(app: FastAPI, name: str) -> dict[str, Any]:
    (row,) = [one for one in await listing(app) if one["Name"] == name]
    return row


def library_count(app: FastAPI) -> int:
    with app.state.sessions.begin() as opened:
        return len(LibraryRepository(opened).all())


async def first_account_token(app: FastAPI) -> str:
    """The first account as `atrium-admin setup` makes it: read into existence, given a password,
    and signed in - so a view is asserted as the account a client would use sees it."""
    assert (await ask(app, LOOPBACK, "GET", "/Startup/User")).status_code == 200
    updated = await ask(app, LOOPBACK, "POST", "/Startup/User", json={"Password": PASSWORD})
    assert updated.status_code == 204, updated.content
    return await token_for(app, LOOPBACK, FIRST_ACCOUNT_NAME)


async def views(app: FastAPI, token: str) -> list[dict[str, Any]]:
    answered = await ask(app, ELSEWHERE, "GET", "/UserViews", token=token)
    assert answered.status_code == 200, answered.content
    rows: list[dict[str, Any]] = answered.json()["Items"]
    return rows


def assert_controller_refusal(answered: httpx.Response) -> None:
    """Behaviours section 1.11's controller refusal: bare `text/plain`, the fixed 25 bytes."""
    assert answered.status_code == 400, answered.content
    assert answered.content == CONTROLLER_ERROR_BODY
    assert answered.headers["content-type"] == "text/plain"


def use_a_fixture_scanner(app: FastAPI) -> Scanner:
    """The server's scanner, rebuilt with the prober the fixture tree's dummy bytes deserve."""
    scanner = Scanner(app.state.sessions, app.state.settings, app.state.paths, prober=not_media)
    app.state.scanner = scanner
    return scanner


# --------------------------------------------------------------------------------------------
# AC-6: POST /Library/Refresh requires an administrator, in both states
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("finished", [False, True], ids=["during setup", "after setup"])
@pytest.mark.parametrize("peer", [LOOPBACK, ELSEWHERE])
@pytest.mark.parametrize(
    ("caller", "status"),
    [("no token", 401), ("non-administrator", 403), ("administrator", 204)],
)
async def test_ac6_refresh_refuses_401_and_403_and_admits_an_administrator(
    server: FastAPI, finished: bool, peer: str, caller: str, status: int
) -> None:
    make_account(server, "Admin", administrator=True)
    make_account(server, "Viewer", administrator=False)
    if finished:
        await finish_setup(server)
    token = None
    if caller != "no token":
        token = await token_for(
            server, ELSEWHERE, "Admin" if caller == "administrator" else "Viewer"
        )

    answered = await ask(server, peer, "POST", REFRESH, token=token)

    assert answered.status_code == status, answered.content
    assert answered.content == b""
    if status != 204:
        assert "content-type" not in answered.headers
        assert server.state.scanner._worker is None, "a refused refresh starts no scan"
    else:
        assert server.state.scanner._worker is not None, "an admitted refresh starts one"


# --------------------------------------------------------------------------------------------
# AC-7: what is added, and what the listing says about it
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("sent", "listed", "on_the_view"), TYPE_TABLE, ids=[str(row[0]) for row in TYPE_TABLE]
)
async def test_ac7_every_type_is_added_listed_and_a_view_before_any_scan(
    server: FastAPI, shelf: Path, sent: str | None, listed: str | None, on_the_view: str | None
) -> None:
    """Spec section 3.6.1's every row: `204`, listed with the type it was stored as - absent,
    never `null`, where there is none - and **a view in the first account's `/UserViews` with no
    scan having run** (operator decision, 2026-09-14), carrying the view's `CollectionType`."""
    token = await first_account_token(server)
    params = {"name": "Shelf", "paths": str(shelf / "films"), "refreshLibrary": "false"}
    if sent is not None:
        params["collectionType"] = sent

    answered = await add(server, **params)

    assert answered.status_code == 204, answered.content
    assert answered.content == b""
    row = await row_named(server, "Shelf")
    assert row["Locations"] == [str(shelf / "films")]
    if listed is None:
        assert "CollectionType" not in row, "absent, never null"
    else:
        assert row["CollectionType"] == listed
    assert server.state.scanner._worker is None, "refreshLibrary=false starts no scan"

    (view,) = [one for one in await views(server, token) if one["Name"] == "Shelf"]
    assert view["Id"] == row["ItemId"]
    assert view["Type"] == "CollectionFolder"
    if on_the_view is None:
        assert "CollectionType" not in view
    else:
        assert view["CollectionType"] == on_the_view


async def test_ac7_a_collection_type_is_matched_ignoring_case(server: FastAPI, shelf: Path) -> None:
    """A vocabulary token in a query is matched ignoring case (behaviours section 1.12)."""
    assert (await add(server, name="Films", collectionType="TvShows")).status_code == 204
    assert (await row_named(server, "Films"))["CollectionType"] == "tvshows"


async def test_ac7_a_library_with_no_paths_is_added_listed_empty_and_a_view(
    server: FastAPI,
) -> None:
    """No `paths` and no body paths: an empty library, listed with none, and a view at once."""
    token = await first_account_token(server)

    answered = await add(server, name="Nothing", collectionType="music")

    assert answered.status_code == 204, answered.content
    row = await row_named(server, "Nothing")
    assert row["Locations"] == []
    assert row["LibraryOptions"] == {"PathInfos": []}
    assert [one["Id"] for one in await views(server, token) if one["Name"] == "Nothing"] == [
        row["ItemId"]
    ]


async def test_ac7_a_listed_row_is_exactly_the_keys_the_reference_sends_byte_for_byte(
    server: FastAPI, shelf: Path
) -> None:
    """The whole body, as bytes: `Name`, `Locations`, `CollectionType`, `LibraryOptions` with its
    one property, `ItemId`, `RefreshStatus` - in the reference's declaration order - and **no
    `PrimaryImageItemId` and no `RefreshProgress`** on an idle row, absent rather than `null`
    `[probe: tools/probe_first_time_setup.py, Jellyfin 10.11.11, 2026-09-14]`."""
    films = str(shelf / "films")
    assert (
        await add(server, name="Movies", collectionType="movies", paths=films)
    ).status_code == 204

    answered = await ask(server, LOOPBACK, "GET", FOLDERS)

    item_id = answered.json()[0]["ItemId"]
    expected = (
        f'[{{"Name":"Movies","Locations":[{json.dumps(films)}],"CollectionType":"movies",'
        f'"LibraryOptions":{{"PathInfos":[{{"Path":{json.dumps(films)}}}]}},'
        f'"ItemId":"{item_id}","RefreshStatus":"Idle"}}]'
    )
    assert answered.content == expected.encode()
    assert len(item_id) == 32 and all(one in "0123456789abcdef" for one in item_id)


async def test_ac7_no_row_carries_a_primary_image_and_library_options_has_one_key(
    server: FastAPI, shelf: Path
) -> None:
    """Over every shape of library at once: typed, untyped, pathless, two paths."""
    await add(server, name="A", collectionType="movies", paths=str(shelf / "films"))
    await add(server, name="B", paths=f"{shelf / 'films'},{shelf / 'shows'}")
    await add(server, name="C", collectionType="books")

    rows = await listing(server)

    assert len(rows) == 3
    for row in rows:
        assert "PrimaryImageItemId" not in row
        assert list(row["LibraryOptions"]) == ["PathInfos"]
        assert [info["Path"] for info in row["LibraryOptions"]["PathInfos"]] == row["Locations"]
        assert set(row) <= {"Name", "Locations", "CollectionType", "LibraryOptions", "ItemId"} | {
            "RefreshStatus"
        }


async def test_ac7_a_name_in_use_is_numbered_from_2_compared_exactly_after_cleaning(
    server: FastAPI,
) -> None:
    """`Movies` twice, then `movies`, then `Movies?`, then `Movies` a third time - the reference's
    reading was `['Movies', 'Movies ', 'Movies2', 'movies']` for the first four
    `[probe: tools/probe_first_time_setup.py, Jellyfin 10.11.11, 2026-09-13]` (behaviours section
    3.30)."""
    for name in ("Movies", "Movies", "movies", "Movies?", "Movies"):
        answered = await add(server, name=name, collectionType="movies")
        assert answered.status_code == 204, (name, answered.content)

    assert sorted(row["Name"] for row in await listing(server)) == [
        "Movies",
        "Movies ",
        "Movies2",
        "Movies3",
        "movies",
    ]


@pytest.mark.parametrize(
    "params",
    [{}, {"name": ""}, {"name": "   "}, {"name": "\t\n"}, {"name": "\u00a0\u2003"}],
    ids=["absent", "empty", "spaces", "tab and line feed", "no-break and em spaces"],
)
async def test_ac7_an_empty_or_whitespace_name_is_the_validation_400_keyed_name(
    server: FastAPI, shelf: Path, params: dict[str, str]
) -> None:
    """Problem details with an `errors` map keyed `name`, and no library added - an empty name and
    a name of spaces measured as one refusal `[probe: tools/probe_first_time_setup.py, Jellyfin
    10.11.11, 2026-09-13]`. The whitespace is the platform's, which is `settle_name`'s rule."""
    answered = await add(server, paths=str(shelf / "films"), **params)

    assert answered.status_code == 400, answered.content
    assert answered.headers["content-type"] == JSON_TYPE
    body = answered.json()
    assert list(body) == ["type", "title", "status", "errors", "traceId"]
    assert body["type"] == PROBLEM_TYPE_BAD_REQUEST
    assert body["title"] == VALIDATION_TITLE
    assert body["status"] == 400
    # The sentence is the reference binder's required-value refusal, read and not measured here.
    assert body["errors"] == {"name": ["The name field is required."]}
    assert library_count(server) == 0


async def test_ac7_the_name_is_keyed_by_its_declared_spelling_whatever_was_sent(
    server: FastAPI,
) -> None:
    answered = await add(server, Name=" ")
    assert answered.status_code == 400
    assert list(answered.json()["errors"]) == ["name"]


async def test_ac7_a_character_the_platform_does_not_call_whitespace_is_a_name(
    server: FastAPI,
) -> None:
    """U+001F is whitespace to Python and not to the reference's rule, so it is not refused - and
    step 3 then replaces it with a space (spec section 3.6.2, read and not measured)."""
    answered = await add(server, name="\x1f")
    assert answered.status_code == 204, answered.content
    assert [row["Name"] for row in await listing(server)] == [" "]


@pytest.mark.parametrize(
    "sent",
    [
        "{root}/nowhere",
        "{root}/a file.txt",
        "films",
        "shelf/films",
        "{root}/films,relative",
        "{root}/outer,{root}/outer/inner",
        "{root}/outer/inner,{root}/outer",
    ],
    ids=[
        "does not exist",
        "not a directory",
        "relative",
        "relative, naming a directory from somewhere",
        "one of two relative",
        "nested",
        "nested, inner first",
    ],
)
async def test_ac7_a_path_that_does_not_exist_is_relative_or_nested_is_refused_and_adds_nothing(
    server: FastAPI, shelf: Path, sent: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`400` `Error processing request.` and no library - the missing path measured on the
    reference, the relative and nested ones this server's divergence (behaviours section 3.31).
    The working directory is the shelf's parent, so `shelf/films` **does** name a directory from
    there and is still refused: a relative path is refused for what it is, not for what it finds."""
    monkeypatch.chdir(shelf.parent)
    assert (shelf.parent / "shelf/films").is_dir()

    answered = await add(server, name="Refused", paths=sent.format(root=shelf))

    assert_controller_refusal(answered)
    assert library_count(server) == 0
    assert await listing(server) == []


async def test_ac7_a_path_given_twice_is_listed_once(server: FastAPI, shelf: Path) -> None:
    films = str(shelf / "films")
    answered = await add(server, name="Twice", paths=f"{films},{films}/,{films}")
    assert answered.status_code == 204, answered.content
    assert (await row_named(server, "Twice"))["Locations"] == [films]


def options_with(*paths: str, **other: Any) -> dict[str, Any]:
    return {"LibraryOptions": {"PathInfos": [{"Path": path} for path in paths], **other}}


async def test_ac7_the_bodys_path_infos_are_the_paths_when_the_query_names_none(
    server: FastAPI, shelf: Path
) -> None:
    body_path = str(shelf / "body")
    answered = await add(server, body=options_with(body_path), name="Body")
    assert answered.status_code == 204, answered.content
    assert (await row_named(server, "Body"))["Locations"] == [body_path]


async def test_ac7_the_bodys_path_infos_are_ignored_when_the_query_names_paths(
    server: FastAPI, shelf: Path
) -> None:
    answered = await add(
        server,
        body=options_with(str(shelf / "body"), "/nowhere/at/all"),
        name="Query",
        paths=str(shelf / "films"),
    )
    assert answered.status_code == 204, answered.content
    assert (await row_named(server, "Query"))["Locations"] == [str(shelf / "films")]


@pytest.mark.parametrize(
    "sent",
    ["{root}/nowhere", "films", "{root}/outer,{root}/outer/inner"],
    ids=["does not exist", "relative", "nested"],
)
async def test_ac7_the_bodys_paths_meet_the_same_rules(
    server: FastAPI, shelf: Path, sent: str
) -> None:
    answered = await add(
        server, body=options_with(*sent.format(root=shelf).split(",")), name="Body"
    )
    assert_controller_refusal(answered)
    assert library_count(server) == 0


async def test_ac7_a_body_path_info_with_no_path_is_refused(server: FastAPI) -> None:
    answered = await add(server, body={"LibraryOptions": {"PathInfos": [{}]}}, name="Body")
    assert_controller_refusal(answered)
    assert library_count(server) == 0


async def test_ac7_every_body_property_but_path_infos_changes_nothing(
    server: FastAPI, shelf: Path
) -> None:
    """A body carrying a spread of the reference's other `LibraryOptions` properties adds the same
    library, listed the same way, as a request carrying none of them (OQ-13, amended 2026-09-14)."""
    films = str(shelf / "films")
    plain = await add(server, name="Plain", collectionType="movies", paths=films)
    dressed = await add(
        server,
        body=options_with(
            str(shelf / "body"),
            Enabled=False,
            EnableRealtimeMonitor=True,
            EnableInternetProviders=True,
            PreferredMetadataLanguage="es",
            MetadataCountryCode="ES",
            TypeOptions=[{"Type": "Movie", "MetadataFetchers": [], "ImageFetchers": []}],
            SeasonZeroDisplayName="Extras",
            CollectionType="books",
            Name="Not this name",
        ),
        name="Dressed",
        collectionType="movies",
        paths=films,
    )
    assert (plain.status_code, dressed.status_code) == (204, 204)

    rows = {row["Name"]: row for row in await listing(server)}
    for row in rows.values():
        del row["Name"], row["ItemId"]
    assert rows["Dressed"] == rows["Plain"]
    with server.state.sessions.begin() as opened:
        stored = {one.name: one for one in LibraryRepository(opened).all()}
    assert (stored["Dressed"].collection_type, stored["Dressed"].roots) == (
        stored["Plain"].collection_type,
        stored["Plain"].roots,
    )
    assert stored["Dressed"].case_sensitive_identity is stored["Plain"].case_sensitive_identity


async def test_ac7_movies_and_movies_are_listed_with_two_item_ids_each_its_own_view(
    server: FastAPI, shelf: Path
) -> None:
    """Behaviours section 3.32: where the reference's listing gives both one `ItemId`, each library
    here keeps its own, and it is the one its view carries."""
    token = await first_account_token(server)
    films = str(shelf / "films")
    assert (
        await add(server, name="Movies", collectionType="movies", paths=films)
    ).status_code == 204
    assert (
        await add(server, name="movies", collectionType="movies", paths=films)
    ).status_code == 204

    listed = {row["Name"]: row["ItemId"] for row in await listing(server)}
    viewed = {row["Name"]: row["Id"] for row in await views(server, token)}

    assert listed["Movies"] != listed["movies"]
    assert listed == {"Movies": viewed["Movies"], "movies": viewed["movies"]}


async def test_ac7_a_scan_adds_no_item_to_a_library_of_a_type_this_server_does_not_scan(
    server: FastAPI, fixture_library: BuiltFixture
) -> None:
    """`books`, and no type, over the fixture tree's films: added with `refreshLibrary=true`,
    scanned, and empty - the accepted gap of behaviours section 5."""
    scanner = use_a_fixture_scanner(server)
    token = await first_account_token(server)
    films = str(fixture_library.of("movies").root)
    for name, params in (("Books", {"collectionType": "books"}), ("Untyped", {})):
        answered = await add(server, name=name, paths=films, refreshLibrary="true", **params)
        assert answered.status_code == 204, answered.content
    await asyncio.wait_for(scanner.idle(), PATIENCE)

    for name in ("Books", "Untyped"):
        item_id = (await row_named(server, name))["ItemId"]
        held = await ask(
            server,
            ELSEWHERE,
            "GET",
            "/Items",
            token=token,
            params={"parentId": item_id, "recursive": "true"},
        )
        assert held.status_code == 200, held.content
        assert held.json()["TotalRecordCount"] == 0, name
    await scanner.stop()


# --------------------------------------------------------------------------------------------
# Spec section 3.5: what the row says while a scan runs
# --------------------------------------------------------------------------------------------


async def test_the_row_is_active_during_the_scan_its_library_was_added_with(
    server: FastAPI, fixture_library: BuiltFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`Active` with a progress while the scan `refreshLibrary=true` started runs, then `Idle`
    with no `RefreshProgress` key - the reference's reading
    `[probe: tools/probe_first_time_setup.py, Jellyfin 10.11.11, 2026-09-13]`."""
    scanner = use_a_fixture_scanner(server)
    gate = Gate()
    wrap_scan(monkeypatch, on_progress=lambda _: gate.hold() if not gate.reached.is_set() else None)
    films = str(fixture_library.of("movies").root)

    answered = await add(
        server, name="Movies", collectionType="movies", paths=films, refreshLibrary="true"
    )
    assert answered.status_code == 204
    await gate.wait_reached()
    during = await row_named(server, "Movies")
    gate.released.set()
    await asyncio.wait_for(scanner.idle(), PATIENCE)
    after = await row_named(server, "Movies")

    assert during["RefreshStatus"] == "Active"
    assert isinstance(during["RefreshProgress"], (int, float))
    assert 0 <= during["RefreshProgress"] <= 100
    assert after["RefreshStatus"] == "Idle"
    assert "RefreshProgress" not in after
    await scanner.stop()
