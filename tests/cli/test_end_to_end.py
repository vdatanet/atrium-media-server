# SPDX-License-Identifier: GPL-3.0-or-later
"""`atrium-admin` against a fresh server, end to end: 014 AC-9.

**Everything the program does is read off the wire.** Each run goes through
`tests/cli/harness.py`'s recording transport from `127.0.0.1`, so what is asserted is the set of
operations it actually sent - not what its source appears to send - and the one operation set spec
section 3.8 allows is compared with it for equality.

The server is built fresh per test on an empty data directory. Its scanner is the real one handed
the fixture tree's prober, and the test - never the client - waits for it to go idle before asking
what a client browsing the library would see.
"""

from __future__ import annotations

import asyncio
import json
import socket
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI

from atrium.cli.client import LibraryRow, device_id
from atrium.cli.commands import settled_names
from tests.cli.harness import (
    LOOPBACK,
    SECTION_3_8,
    SERVER,
    RecordingTransport,
    invoke,
    piped,
)
from tests.conformance.test_setup_window import ELSEWHERE, ask, sign_in
from tests.fixtures.library import BuiltFixture
from tests.library.test_scanner import PATIENCE

PASSWORD = "an administrator's password"
ADMIN = "joan"

PUBLIC = ("GET", "/System/Info/Public")
SIGN_IN = ("POST", "/Users/AuthenticateByName")
LISTING = ("GET", "/Library/VirtualFolders")
ADDING = ("POST", "/Library/VirtualFolders")
REFRESH = ("POST", "/Library/Refresh")

ROOT = Path(__file__).resolve().parents[2]


def signed(*argv: str) -> tuple[str, ...]:
    """The arguments a command signs in with, as the first administrator."""
    return (*argv, "--server", SERVER, "--username", ADMIN, "--password-stdin")


async def browse(app: FastAPI, name: str) -> tuple[bool, int]:
    """Whether the administrator the client made sees the library as a view, and how many films
    `/Items` finds under it - asked as an unmodified client asks, from elsewhere, signed in."""
    answered = await sign_in(app, ELSEWHERE, ADMIN, PASSWORD)
    assert answered.status_code == 200, answered.content
    token = answered.json()["AccessToken"]
    viewed = await ask(app, ELSEWHERE, "GET", "/UserViews", token=token)
    assert viewed.status_code == 200, viewed.content
    ids = [row["Id"] for row in viewed.json()["Items"] if row["Name"] == name]
    if not ids:
        return False, 0
    films = await ask(
        app,
        ELSEWHERE,
        "GET",
        "/Items",
        token=token,
        params={"parentId": ids[0], "recursive": "true", "includeItemTypes": "Movie"},
    )
    assert films.status_code == 200, films.content
    return True, int(films.json()["TotalRecordCount"])


# --------------------------------------------------------------------------------------------
# AC-9: the four commands, and nothing but section 3.8's operations
# --------------------------------------------------------------------------------------------


async def test_ac9_the_four_commands_set_up_a_fresh_server_and_send_only_section_3_8(
    server: FastAPI, fixture_library: BuiltFixture
) -> None:
    """setup, then library add over the fixture tree's films, then library list and library scan -
    the whole run's operations equal to section 3.8's, and the library browsable as the
    administrator the client created once the scan it started has finished."""
    wire = RecordingTransport(server, LOOPBACK)

    setup = await invoke(
        wire, "setup", "--server", SERVER, "--username", ADMIN, "--password-stdin",
        stdin=piped(PASSWORD),
    )  # fmt: skip
    assert (setup.code, setup.stderr) == (0, ""), setup.stderr
    assert setup.stdout == f"{ADMIN}\n", "setup prints the administrator's name"
    assert setup.operations == [
        PUBLIC,
        ("GET", "/Startup/User"),
        ("POST", "/Startup/User"),
        ("POST", "/Startup/Complete"),
    ]
    assert server.state.server_state.startup_wizard_completed is True

    films = str(fixture_library.of("movies").root)
    added = await invoke(
        wire, *signed("library", "add", "--type", "movies", "Films", films), stdin=piped(PASSWORD)
    )
    assert (added.code, added.stderr) == (0, ""), added.stderr
    assert added.stdout == "Films\n"
    assert added.operations == [PUBLIC, SIGN_IN, LISTING, ADDING, LISTING]
    (adding,) = [one for one in added.sent if one.operation == ADDING]
    assert "refreshLibrary=true" in adding.url, "the add starts the library's scan"

    await asyncio.wait_for(server.state.scanner.idle(), PATIENCE)

    listed = await invoke(wire, *signed("library", "list"), stdin=piped(PASSWORD))
    assert (listed.code, listed.stderr) == (0, ""), listed.stderr
    assert listed.stdout == f"Films\tmovies\t{films}\n"
    assert listed.operations == [PUBLIC, SIGN_IN, LISTING]

    scanned = await invoke(wire, *signed("library", "scan"), stdin=piped(PASSWORD))
    assert (scanned.code, scanned.stderr) == (0, ""), scanned.stderr
    assert "scan of every library was started" in scanned.stdout
    assert scanned.operations == [PUBLIC, SIGN_IN, REFRESH]
    assert [one for one in scanned.operations if one not in (PUBLIC, SIGN_IN)] == [REFRESH], (
        "library scan issues POST /Library/Refresh once and nothing to learn whether it finished"
    )
    await asyncio.wait_for(server.state.scanner.idle(), PATIENCE)

    assert {one.operation for one in wire.sent} == SECTION_3_8
    viewed, count = await browse(server, "Films")
    assert viewed
    assert count > 0


async def test_ac9_during_setup_from_loopback_the_library_commands_sign_in_as_nobody(
    server: FastAPI, tmp_path: Path
) -> None:
    """The window admits a caller from this machine with no credentials (spec section 3.1), so
    `library add` and `library list` send no sign-in and need no `--username`."""
    wire = RecordingTransport(server, LOOPBACK)
    shelf = tmp_path / "shelf"
    shelf.mkdir()

    added = await invoke(wire, "library", "add", "--server", SERVER, "Shelf", str(shelf))
    assert (added.code, added.stderr, added.stdout) == (0, "", "Shelf\n")
    listed = await invoke(wire, "library", "list", "--server", SERVER)
    assert (listed.code, listed.stdout) == (0, f"Shelf\t-\t{shelf}\n")

    assert SIGN_IN not in {one.operation for one in wire.sent}
    assert all("Token=" not in one.header("Authorization") for one in wire.sent)
    assert server.state.server_state.startup_wizard_completed is False


async def test_ac9_library_add_prints_the_name_the_library_ended_up_with(
    server: FastAPI, tmp_path: Path
) -> None:
    """Numbered from `2` when the name is taken, and cleaned as section 3.6.2 cleans it - over the
    same path and type every time, so neither can be what the name is found by."""
    wire = RecordingTransport(server, LOOPBACK)
    shelf = tmp_path / "shelf"
    shelf.mkdir()

    printed = []
    for asked in ("Movies", "Movies", "Movies?", "Movies"):
        ran = await invoke(
            wire, "library", "add", "--server", SERVER, "--type", "movies", asked, str(shelf)
        )
        assert (ran.code, ran.stderr) == (0, ""), ran.stderr
        printed.append(ran.stdout)
    assert printed == ["Movies\n", "Movies2\n", "Movies \n", "Movies3\n"]


def test_the_added_name_is_the_one_the_earlier_listing_lacked() -> None:
    """`settled_names` alone, including the case a live server cannot stage on demand: another
    library added between the two listings, told apart by type, and reported when it cannot be."""
    before = [LibraryRow("Movies", "movies", ("/a",))]
    mine = LibraryRow("Movies2", "movies", ("/a",))
    theirs = LibraryRow("Music", "music", ("/a",))
    other_films = LibraryRow("Films", "movies", ("/b",))

    assert settled_names(before, [*before, mine], "movies") == ["Movies2"]
    assert settled_names(before, [*before, theirs, mine], "movies") == ["Movies2"]
    assert settled_names(before, [*before, other_films, mine], "movies") == ["Films", "Movies2"]
    assert settled_names(before, [*before, theirs, mine], "photos") == ["Music", "Movies2"]


async def test_ac9_every_request_is_one_device_and_signing_in_again_replaces_its_token(
    server: FastAPI,
) -> None:
    """OQ-9: no token is kept, and each command signs in again **as the same device**, so a
    second invocation's token replaces the first's rather than adding a session beside it."""
    wire = RecordingTransport(server, LOOPBACK)
    setup = await invoke(
        wire, "setup", "--server", SERVER, "--username", ADMIN, "--password-stdin",
        stdin=piped(PASSWORD),
    )  # fmt: skip
    assert setup.code == 0, setup.stderr

    tokens = []
    for _ in range(2):
        ran = await invoke(wire, *signed("library", "list"), stdin=piped(PASSWORD))
        assert ran.code == 0, ran.stderr
        (signing_in,) = [one for one in ran.sent if one.operation == SIGN_IN]
        tokens.append(json.loads(signing_in.answer)["AccessToken"])

    expected = f'DeviceId="{device_id()}"'
    assert device_id() == f"atrium-admin-{socket.gethostname()}"
    assert all(expected in one.header("Authorization") for one in wire.sent)
    first, second = tokens
    assert first != second
    assert (await ask(server, ELSEWHERE, "GET", "/Users/Me", token=first)).status_code == 401
    assert (await ask(server, ELSEWHERE, "GET", "/Users/Me", token=second)).status_code == 200


# --------------------------------------------------------------------------------------------
# It is installed as the program the spec names
# --------------------------------------------------------------------------------------------


def test_the_atrium_admin_script_is_declared() -> None:
    declared: dict[str, Any] = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))
    assert declared["project"]["scripts"]["atrium-admin"] == "atrium.cli.commands:main"


def test_python_dash_m_atrium_cli_runs_the_program() -> None:
    ran = subprocess.run(
        [sys.executable, "-m", "atrium.cli", "--help"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout.startswith("usage: atrium-admin")
    for command in ("setup", "library"):
        assert command in ran.stdout


@pytest.mark.parametrize("command", [["setup"], ["library", "add"], ["library", "list"]])
async def test_every_command_has_help(server: FastAPI, command: list[str]) -> None:
    ran = await invoke(RecordingTransport(server, LOOPBACK), *command, "--help")
    assert ran.code == 0
    assert "--server URL" in ran.stdout
    assert ran.sent == []
