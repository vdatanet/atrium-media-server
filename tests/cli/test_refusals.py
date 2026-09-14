# SPDX-License-Identifier: GPL-3.0-or-later
"""What `atrium-admin` refuses, what it prints when the server refuses, and where a password goes:
014 AC-10.

Three kinds of refusal and three exit codes. **`2`** is this program refusing before it sends what
it refuses - `setup` on a finished server or at an address that is not loopback, a password with
nowhere to come from, an argument error. **`1`** is the server refusing, printed as `<status>
<reason>` in whichever of the reference's shapes the reason came, or an address that does not answer
as a Jellyfin server. What each run sent is read off the recording transport, so *"refused without
calling sections 3.2 to 3.4"* is a list of requests and not a reading of the source.
"""

from __future__ import annotations

import ast
import getpass
import io
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from atrium.cli import commands
from atrium.cli.commands import build_parser, is_loopback_host
from atrium.compat.guids import new_id
from atrium.db.repositories import UserRepository
from atrium.domain.user import User
from tests.cli.harness import (
    CARRY_THE_PASSWORD,
    LOOPBACK,
    SERVER,
    Ran,
    RecordingTransport,
    Terminal,
    invoke,
    piped,
)
from tests.conformance.test_setup_window import THIS_MACHINE_ON_THE_LAN, ask

#: A password nothing else in the run could contain by accident.
SENTINEL = "sentinel-7f3a9c-password"
ADMIN = "joan"

PUBLIC = ("GET", "/System/Info/Public")
SETUP_OPERATIONS = {
    ("GET", "/Startup/User"),
    ("POST", "/Startup/User"),
    ("POST", "/Startup/Complete"),
}

SRC = Path(__file__).resolve().parents[2] / "src" / "atrium" / "cli"


def setup_argv(server: str = SERVER, username: str = ADMIN) -> tuple[str, ...]:
    return ("setup", "--server", server, "--username", username, "--password-stdin")


async def set_up(wire: RecordingTransport, password: str = SENTINEL) -> None:
    ran = await invoke(wire, *setup_argv(), stdin=piped(password))
    assert ran.code == 0, ran.stderr


def add_account(app: FastAPI, name: str, password: str, *, administrator: bool) -> None:
    with app.state.sessions.begin() as opened:
        UserRepository(opened).add(
            User(
                id=new_id(),
                name=name,
                is_administrator=administrator,
                password_hash=app.state.passwords.hash(password),
            )
        )


def account_count(app: FastAPI) -> int:
    with app.state.sessions.begin() as opened:
        return UserRepository(opened).count()


def assert_server_refusal(ran: Ran, operation: tuple[str, str], status_and_reason: str) -> None:
    """Exit `1`, and the refusal printed with the operation, the status and the reason."""
    assert ran.code == 1, (ran.stdout, ran.stderr)
    assert ran.operations[-1] == operation, "nothing is sent after a refusal"
    assert ran.sent[-1].status == int(status_and_reason.split()[0])
    assert ran.stderr == (
        f"atrium-admin: {operation[0]} {operation[1]} was refused: {status_and_reason}\n"
    )
    assert ran.stdout == ""


# --------------------------------------------------------------------------------------------
# setup refuses before any setup operation
# --------------------------------------------------------------------------------------------


async def test_ac10_setup_refuses_a_finished_server_without_calling_3_2_to_3_4(
    server: FastAPI,
) -> None:
    wire = RecordingTransport(server, LOOPBACK)
    assert (await ask(server, LOOPBACK, "POST", "/Startup/Complete")).status_code == 204

    ran = await invoke(wire, *setup_argv(), stdin=piped(SENTINEL))

    assert ran.code == 2
    assert ran.operations == [PUBLIC]
    assert "setup is already finished" in ran.stderr
    assert ran.stdout == ""
    assert account_count(server) == 0


@pytest.mark.parametrize(
    "address",
    ["http://192.168.1.10:8096", "http://atrium.local:8096", "http://[fe80::1]:8096"],
)
async def test_ac10_setup_refuses_an_address_that_is_not_loopback_during_setup(
    server: FastAPI, address: str
) -> None:
    """Refused with no setup operation sent, saying it must run on the server's machine - here the
    client is on the server's machine and addresses it by a network address, which spec section
    3.1 calls a caller from elsewhere."""
    wire = RecordingTransport(server, THIS_MACHINE_ON_THE_LAN)

    ran = await invoke(wire, *setup_argv(server=address), stdin=piped(SENTINEL))

    assert ran.code == 2
    assert ran.operations == [PUBLIC]
    assert not SETUP_OPERATIONS & set(ran.operations)
    assert "has to run on the server's own machine" in ran.stderr
    assert "http://127.0.0.1:8096" in ran.stderr, "and names the address it would work at"
    assert "reverse proxy" in ran.stderr, "plan section 9: the caveat is in the refusal text"
    assert account_count(server) == 0
    assert server.state.server_state.startup_wizard_completed is False


@pytest.mark.parametrize(
    ("host", "loopback"),
    [
        ("127.0.0.1", True),
        ("127.8.9.10", True),
        ("::1", True),
        ("[::1]", True),
        ("::ffff:127.0.0.1", True),
        ("localhost", True),
        ("LocalHost.", True),
        ("192.168.1.10", False),
        ("0.0.0.0", False),  # noqa: S104 - an address read, not bound
        ("::", False),
        ("::ffff:192.168.1.10", False),
        ("localhost.example.com", False),
        ("atrium", False),
    ],
)
def test_ac10_loopback_is_decided_from_the_address_as_written(host: str, loopback: bool) -> None:
    """No name is looked up: `localhost` is the one name, and every other is not loopback."""
    assert is_loopback_host(host) is loopback


async def test_ac10_a_request_the_client_believed_local_is_decided_by_the_server(
    server: FastAPI, tmp_path: Path
) -> None:
    """A tunnel whose far end reaches the server by a network address: the address is loopback to
    the client and not to the server, which refuses - and the refusal is printed like any other."""
    wire = RecordingTransport(server, THIS_MACHINE_ON_THE_LAN)
    ran = await invoke(wire, "library", "add", "--server", SERVER, "Films", str(tmp_path))
    assert_server_refusal(ran, ("GET", "/Library/VirtualFolders"), "401 Unauthorized")


# --------------------------------------------------------------------------------------------
# A server refusal per command: exit 1, status and reason
# --------------------------------------------------------------------------------------------


async def test_ac10_setup_prints_the_bare_string_refusal_and_does_not_complete(
    server: FastAPI,
) -> None:
    wire = RecordingTransport(server, LOOPBACK)
    ran = await invoke(wire, *setup_argv(), stdin=piped(""))
    assert_server_refusal(ran, ("POST", "/Startup/User"), "400 Password must not be empty")
    assert ("POST", "/Startup/Complete") not in ran.operations
    assert server.state.server_state.startup_wizard_completed is False


async def test_ac10_setup_prints_the_controller_refusal_of_a_name(server: FastAPI) -> None:
    wire = RecordingTransport(server, LOOPBACK)
    ran = await invoke(wire, *setup_argv(username="not/valid"), stdin=piped(SENTINEL))
    assert_server_refusal(ran, ("POST", "/Startup/User"), "400 Error processing request.")
    assert server.state.server_state.startup_wizard_completed is False


async def test_ac10_library_add_prints_a_path_refusal(server: FastAPI, tmp_path: Path) -> None:
    wire = RecordingTransport(server, LOOPBACK)
    missing = str(tmp_path / "not there")
    ran = await invoke(wire, "library", "add", "--server", SERVER, "Films", missing)
    assert_server_refusal(ran, ("POST", "/Library/VirtualFolders"), "400 Error processing request.")


async def test_ac10_library_add_prints_a_validation_refusal_with_what_it_names(
    server: FastAPI, tmp_path: Path
) -> None:
    wire = RecordingTransport(server, LOOPBACK)
    ran = await invoke(wire, "library", "add", "--server", SERVER, "   ", str(tmp_path))
    assert_server_refusal(
        ran,
        ("POST", "/Library/VirtualFolders"),
        "400 One or more validation errors occurred. name: The name field is required.",
    )


async def test_ac10_library_list_prints_the_empty_403_of_a_non_administrator(
    server: FastAPI,
) -> None:
    wire = RecordingTransport(server, LOOPBACK)
    await set_up(wire)
    add_account(server, "viewer", SENTINEL, administrator=False)
    ran = await invoke(
        wire,
        *("library", "list", "--server", SERVER, "--username", "viewer", "--password-stdin"),
        stdin=piped(SENTINEL),
    )
    assert_server_refusal(ran, ("GET", "/Library/VirtualFolders"), "403 Forbidden")


async def test_ac10_library_scan_prints_the_empty_403_of_a_non_administrator(
    server: FastAPI,
) -> None:
    wire = RecordingTransport(server, LOOPBACK)
    await set_up(wire)
    add_account(server, "viewer", SENTINEL, administrator=False)
    ran = await invoke(
        wire,
        *("library", "scan", "--server", SERVER, "--username", "viewer", "--password-stdin"),
        stdin=piped(SENTINEL),
    )
    assert_server_refusal(ran, ("POST", "/Library/Refresh"), "403 Forbidden")
    assert server.state.scanner._worker is None


async def test_ac10_a_refused_sign_in_is_printed_and_nothing_follows_it(server: FastAPI) -> None:
    wire = RecordingTransport(server, LOOPBACK)
    await set_up(wire)
    ran = await invoke(
        wire,
        *("library", "scan", "--server", SERVER, "--username", ADMIN, "--password-stdin"),
        stdin=piped("not the password"),
    )
    assert_server_refusal(
        ran, ("POST", "/Users/AuthenticateByName"), "401 Error processing request."
    )


async def test_ac10_after_setup_the_library_commands_need_a_username(server: FastAPI) -> None:
    wire = RecordingTransport(server, LOOPBACK)
    await set_up(wire)
    ran = await invoke(wire, "library", "list", "--server", SERVER)
    assert ran.code == 2
    assert ran.operations == [PUBLIC]
    assert "pass --username" in ran.stderr


# --------------------------------------------------------------------------------------------
# An address that is not a Jellyfin server
# --------------------------------------------------------------------------------------------


async def test_an_address_where_nothing_answers_exits_1() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    ran = await invoke(
        httpx.MockTransport(refuse), *setup_argv(), stdin=piped(SENTINEL)
    )  # fmt: skip
    assert ran.code == 1
    assert ran.stderr.startswith(f"atrium-admin: nothing answered at {SERVER}: ConnectError")


@pytest.mark.parametrize("body", [{"ServerName": "something"}, {"ProductName": ""}, ["a list"]])
async def test_an_address_with_no_product_name_exits_1_and_is_sent_no_password(
    body: object,
) -> None:
    seen: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=body)

    ran = await invoke(
        httpx.MockTransport(answer),
        *("library", "scan", "--server", SERVER, "--username", ADMIN, "--password-stdin"),
        stdin=piped(SENTINEL),
    )
    assert ran.code == 1
    assert "does not answer as a Jellyfin server" in ran.stderr
    assert [request.url.path for request in seen] == ["/System/Info/Public"]


# --------------------------------------------------------------------------------------------
# Arguments refused locally
# --------------------------------------------------------------------------------------------


COMMANDS = (["setup"], ["library", "add"], ["library", "list"], ["library", "scan"])


@pytest.mark.parametrize("command", COMMANDS, ids=" ".join)
@pytest.mark.parametrize(
    "spelling",
    [["--password", SENTINEL], [f"--password={SENTINEL}"], ["--pass", SENTINEL], ["-p", SENTINEL]],
    ids=lambda spelling: spelling[0].split("=")[0],
)
async def test_ac10_no_argument_takes_a_password(
    server: FastAPI, command: list[str], spelling: list[str]
) -> None:
    """No `--password`, and no abbreviation of `--password-stdin` that would swallow one."""
    wire = RecordingTransport(server, LOOPBACK)
    tail = ["Films", "/srv"] if command == ["library", "add"] else []
    ran = await invoke(
        wire, *command, "--server", SERVER, "--username", ADMIN, *spelling, *tail
    )  # fmt: skip
    assert ran.code == 2
    assert ran.sent == []
    assert SENTINEL not in ran.stdout


def test_ac10_the_only_password_option_is_password_stdin() -> None:
    """Every option of every parser, read off the parsers themselves."""
    parser = build_parser()
    found: set[str] = set()

    def walk(one: object) -> None:
        for action in getattr(one, "_actions", []):
            found.update(action.option_strings)
            for sub in (getattr(action, "choices", None) or {}).values():
                if hasattr(sub, "_actions"):
                    walk(sub)

    walk(parser)
    assert "--server" in found, "the walk reached the commands' own parsers"
    assert {one for one in found if "pass" in one.lower()} == {"--password-stdin"}
    assert all(
        getattr(sub, "allow_abbrev", True) is False
        for sub in [parser, *_parsers(parser)]
    ), "no option may be reached by a prefix"  # fmt: skip


def _parsers(parser: object) -> list[object]:
    found = []
    for action in getattr(parser, "_actions", []):
        for sub in (getattr(action, "choices", None) or {}).values():
            if hasattr(sub, "_actions"):
                found += [sub, *_parsers(sub)]
    return found


async def test_ac10_the_server_address_is_required(server: FastAPI) -> None:
    wire = RecordingTransport(server, LOOPBACK)
    ran = await invoke(wire, "library", "list")
    assert ran.code == 2
    assert "--server" in ran.stderr
    assert ran.sent == []


@pytest.mark.parametrize("command", [["setup"], ["library", "scan"]], ids=" ".join)
async def test_ac10_with_no_terminal_and_no_password_stdin_nothing_is_sent(
    server: FastAPI, command: list[str]
) -> None:
    wire = RecordingTransport(server, LOOPBACK)
    ran = await invoke(wire, *command, "--server", SERVER, "--username", ADMIN)
    assert ran.code == 2
    assert "--password-stdin" in ran.stderr
    assert ran.sent == []


async def test_a_path_holding_a_comma_is_refused_before_anything_is_sent(
    server: FastAPI,
) -> None:
    wire = RecordingTransport(server, LOOPBACK)
    ran = await invoke(wire, "library", "add", "--server", SERVER, "Films", "/srv/a,b")
    assert ran.code == 2
    assert ran.sent == []


# --------------------------------------------------------------------------------------------
# Where a password goes
# --------------------------------------------------------------------------------------------


async def test_ac10_on_a_terminal_the_password_is_asked_for_without_being_shown(
    server: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A terminal is asked through `getpass`, which reads without echoing, prompting on standard
    error; `--password-stdin` is not needed there."""
    asked: list[tuple[str, object]] = []

    def typed(prompt: str = "Password: ", stream: object = None) -> str:
        asked.append((prompt, stream))
        return SENTINEL

    monkeypatch.setattr(getpass, "getpass", typed)
    wire = RecordingTransport(server, LOOPBACK)
    terminal = Terminal("")
    ran = await invoke(
        wire, "setup", "--server", SERVER, "--username", ADMIN, stdin=terminal
    )  # fmt: skip

    assert ran.code == 0, ran.stderr
    assert len(asked) == 1
    (signing_up,) = [one for one in ran.sent if one.operation == ("POST", "/Startup/User")]
    assert SENTINEL.encode() in signing_up.body
    assert SENTINEL not in ran.stdout + ran.stderr


async def test_ac10_the_password_is_in_no_output_and_no_request_but_the_two_that_carry_it(
    server: FastAPI, tmp_path: Path
) -> None:
    """The sentinel sweep: every command, a success and a refusal among them, and every stream and
    every recorded request - address, headers and body - searched for it."""
    wire = RecordingTransport(server, LOOPBACK)
    shelf = tmp_path / "shelf"
    shelf.mkdir()

    def signed(*argv: str, username: str = ADMIN) -> tuple[str, ...]:
        return (*argv, "--server", SERVER, "--username", username, "--password-stdin")

    runs = [await invoke(wire, *setup_argv(username=ADMIN), stdin=piped(SENTINEL))]
    add_account(server, "viewer", SENTINEL, administrator=False)
    runs += [
        await invoke(wire, *signed("library", "add", "Shelf", str(shelf)), stdin=piped(SENTINEL)),
        await invoke(wire, *signed("library", "list"), stdin=piped(SENTINEL)),
        await invoke(wire, *signed("library", "scan"), stdin=piped(SENTINEL)),
        await invoke(wire, *signed("library", "scan", username="viewer"), stdin=piped(SENTINEL)),
        await invoke(wire, *signed("library", "list", username="nobody"), stdin=piped(SENTINEL)),
    ]
    assert [ran.code for ran in runs] == [0, 0, 0, 0, 1, 1], [ran.stderr for ran in runs]
    await server.state.scanner.idle()

    for ran in runs:
        assert SENTINEL not in ran.stdout
        assert SENTINEL not in ran.stderr

    carried = set()
    for sent in wire.sent:
        assert SENTINEL not in sent.url
        assert all(SENTINEL not in key + value for key, value in sent.headers)
        assert SENTINEL.encode() not in sent.answer
        if SENTINEL.encode() in sent.body:
            assert sent.operation in CARRY_THE_PASSWORD, sent.operation
            carried.add(sent.operation)
    assert carried == CARRY_THE_PASSWORD, "the sweep searched requests that carry the password"


def test_ac10_the_client_reads_no_environment() -> None:
    """*"From nothing else, the environment included"* (spec section 3.8): no module of the client
    imports `os` or names `environ` or `getenv`."""
    for module in sorted(SRC.glob("*.py")):
        tree = ast.parse(module.read_text(encoding="utf-8"))
        imported = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import | ast.ImportFrom)
            for alias in (
                node.names if isinstance(node, ast.Import) else [ast.alias(name=node.module or "")]
            )
        }
        names = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)} | {
            node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
        }
        assert "os" not in imported, module.name
        assert not {"environ", "getenv"} & names, module.name


def test_the_standard_input_line_loses_its_line_ending_and_nothing_else() -> None:
    read = commands.password_reader(True, io.StringIO(f"  {SENTINEL} \r\nsecond\n"), io.StringIO())
    assert read() == f"  {SENTINEL} "
