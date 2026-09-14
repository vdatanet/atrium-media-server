# SPDX-License-Identifier: GPL-3.0-or-later
"""`atrium-admin` - arguments, passwords, output and exit codes (014 spec section 3.8).

    atrium-admin setup --server URL --username NAME [--password-stdin]
    atrium-admin library add --server URL [--username NAME] [--password-stdin] [--type TYPE]
                             NAME PATH [PATH ...]
    atrium-admin library list --server URL [--username NAME] [--password-stdin]
    atrium-admin library scan --server URL --username NAME [--password-stdin]

**Exit codes.** `0` a success; `1` the server refused, or did not answer as a Jellyfin server -
a refusal is printed as `<status> <reason>`; `2` this program refused before sending what it
refused, including every argument error.

**What it promises an operator** (spec section 3.8):

- **The address is required and never guessed**: `--server` has no default.
- **A password is never an argument.** It is asked for on a terminal without being shown, or read
  as one line from standard input with `--password-stdin` - and from nothing else, the environment
  included. There is no `--password`, and no option may be abbreviated, so `--password` cannot
  reach `--password-stdin` by prefix either.
- **Every command reads `GET /System/Info/Public` first**, so nothing - a password least of all -
  is sent to an address that does not answer as a Jellyfin server.
- **`setup` refuses before any setup operation** a server whose setup is finished, and an address
  that is not a loopback address while it is unfinished. That second check is a courtesy decided
  here from the address as written - a literal loopback address or the name `localhost`, and no
  name is looked up - and the server's own rule decides: a request this program believed local
  and the server does not is refused there, and printed like any other refusal.
- **The library commands sign in only when the server needs it**: during setup, from a loopback
  address, the window admits them with no credentials; otherwise they sign in with `--username`.
  `library scan` always signs in, because `POST /Library/Refresh` requires an administrator in
  both states.

See specs/014-first-time-setup/plan.md section 6.7.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import ipaddress
import sys
from collections.abc import Callable, Sequence
from contextlib import redirect_stderr, redirect_stdout
from typing import Final, TextIO

import httpx

from atrium.cli.client import (
    AdminClient,
    LibraryRow,
    PublicInfo,
    Refused,
    UnexpectedAnswerError,
    UnreachableError,
)

PROGRAM: Final = "atrium-admin"

#: Exit codes.
SUCCESS: Final = 0
SERVER_REFUSED: Final = 1
LOCALLY_REFUSED: Final = 2


class LocalRefusalError(Exception):
    """This program refuses, before sending what it refuses."""


# --------------------------------------------------------------------------------------------
# Addresses and passwords
# --------------------------------------------------------------------------------------------


def is_loopback_host(host: str) -> bool:
    """Whether an address, **as written**, names this machine's loopback.

    A literal IPv4 or IPv6 loopback address - the IPv4-mapped form included - or the name
    `localhost`. No name is looked up: the check is a courtesy the server's rule decides (spec
    section 3.8), and a lookup would make it answer differently from one resolver to the next.
    """
    name = host.strip().strip("[]").rstrip(".").lower()
    if name == "localhost":
        return True
    try:
        address = ipaddress.ip_address(name.split("%")[0])
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return address.ipv4_mapped.is_loopback
    return address.is_loopback


def _server_url(value: str) -> str:
    """`--server`: an `http://` or `https://` address with a host, and nothing guessed."""
    try:
        url = httpx.URL(value)
    except httpx.InvalidURL as exc:
        raise argparse.ArgumentTypeError(f"{value!r} is not an address: {exc}") from exc
    if url.scheme not in ("http", "https") or not url.host:
        raise argparse.ArgumentTypeError(
            f"{value!r} is not an http:// or https:// address, such as http://127.0.0.1:8096"
        )
    return value


def _is_terminal(stream: TextIO) -> bool:
    try:
        return stream.isatty()
    except (AttributeError, ValueError):
        return False


def password_reader(from_stdin: bool, stdin: TextIO, stderr: TextIO) -> Callable[[], str]:
    """Where the password will come from, decided before any request is sent (plan 6.7).

    Reading is deferred to the moment a password is needed, so a command refused before then
    never asks for one. Standard input gives one line, its line ending removed and nothing else.
    """
    if from_stdin:

        def from_standard_input() -> str:
            line = stdin.readline()
            return line.removesuffix("\n").removesuffix("\r")

        return from_standard_input
    if _is_terminal(stdin):
        return lambda: getpass.getpass("Password: ", stream=stderr)
    raise LocalRefusalError(
        "there is no terminal to ask for the password on. Write it to standard input and pass "
        "--password-stdin; it is never accepted as an argument."
    )


# --------------------------------------------------------------------------------------------
# The arguments
# --------------------------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Every parser refuses abbreviations, so no prefix of an option is an option."""
    common = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    common.add_argument(
        "--server",
        required=True,
        metavar="URL",
        type=_server_url,
        help="the server's address, for example http://127.0.0.1:8096 - required, never guessed",
    )
    common.add_argument(
        "--password-stdin",
        action="store_true",
        help="read the password as one line from standard input instead of asking on a terminal",
    )

    parser = argparse.ArgumentParser(
        prog=PROGRAM,
        description="Set up an Atrium server and manage its libraries, over its HTTP API.",
        allow_abbrev=False,
    )
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    setup = commands.add_parser(
        "setup",
        parents=[common],
        allow_abbrev=False,
        help="create the first administrator and finish setup",
        description="Create the first administrator, give it a name and a password, and finish "
        "setup. Runs on the server's own machine, against a loopback address.",
    )
    setup.add_argument("--username", required=True, metavar="NAME", help="the administrator's name")

    library = commands.add_parser(
        "library", allow_abbrev=False, help="add, list and scan libraries"
    )
    library_commands = library.add_subparsers(
        dest="library_command", required=True, metavar="COMMAND"
    )
    sign_in = "the administrator to sign in as; not needed during setup from a loopback address"

    add = library_commands.add_parser(
        "add",
        parents=[common],
        allow_abbrev=False,
        help="add a library and start its scan",
        description="Add a library over one or more directories on the server, start its scan, "
        "and print the name it was added under - which is numbered when the name is taken.",
    )
    add.add_argument("--username", metavar="NAME", help=sign_in)
    add.add_argument(
        "--type",
        dest="kind",
        metavar="TYPE",
        help="movies, tvshows or music are scanned; any other type, or none, is an empty library",
    )
    add.add_argument("name", metavar="NAME", help="the library's name")
    add.add_argument("paths", nargs="+", metavar="PATH", help="an absolute path on the server")

    listing = library_commands.add_parser(
        "list",
        parents=[common],
        allow_abbrev=False,
        help="list the libraries",
        description="One line per library: its name, its type ('-' for none) and its paths, "
        "separated by tabs.",
    )
    listing.add_argument("--username", metavar="NAME", help=sign_in)

    scan = library_commands.add_parser(
        "scan",
        parents=[common],
        allow_abbrev=False,
        help="start a scan of every library",
        description="Start a scan of every library and exit without waiting for it.",
    )
    scan.add_argument(
        "--username", required=True, metavar="NAME", help="the administrator to sign in as"
    )
    return parser


# --------------------------------------------------------------------------------------------
# The commands
# --------------------------------------------------------------------------------------------


def _write(stream: TextIO, line: str) -> None:
    stream.write(f"{line}\n")


def _setup_elsewhere(server: str, host: str) -> str:
    url = httpx.URL(server)
    port = f":{url.port}" if url.port is not None else ""
    example = f"{url.scheme}://127.0.0.1{port}"
    return (
        f"setup has to run on the server's own machine, against a loopback address such as "
        f"{example} - {host} is not one. While setup is unfinished the server admits a caller "
        f"with no credentials from a loopback address only, and would refuse this one. A reverse "
        f"proxy on the server's machine does not make its callers local: finish setup before "
        f"putting one in front of the server. No setup operation was sent."
    )


async def _setup(
    args: argparse.Namespace,
    client: AdminClient,
    info: PublicInfo,
    password: Callable[[], str],
    stdout: TextIO,
) -> int:
    """GET then POST `/Startup/User`, then `POST /Startup/Complete` (spec sections 3.2-3.4)."""
    if info.startup_wizard_completed:
        raise LocalRefusalError(
            f"setup is already finished on {args.server}, and nothing was changed. The library "
            f"commands sign in as an administrator with --username."
        )
    host = httpx.URL(args.server).host
    if not is_loopback_host(host):
        raise LocalRefusalError(_setup_elsewhere(args.server, host))
    secret = password()
    await client.first_user()
    await client.update_first_user(args.username, secret)
    await client.complete()
    _write(stdout, args.username)
    return SUCCESS


async def _sign_in_if_needed(
    args: argparse.Namespace,
    client: AdminClient,
    info: PublicInfo,
    password: Callable[[], str] | None,
) -> None:
    """No credentials during setup from a loopback address (spec 3.1); an administrator else."""
    host = httpx.URL(args.server).host
    if not info.startup_wizard_completed and is_loopback_host(host):
        return
    if args.username is None or password is None:
        why = (
            "setup is finished"
            if info.startup_wizard_completed
            else f"{host} is not a loopback address"
        )
        raise LocalRefusalError(
            f"this command signs in as an administrator here, because {why}: pass --username."
        )
    await client.sign_in(args.username, password())


def settled_names(before: list[LibraryRow], after: list[LibraryRow], kind: str | None) -> list[str]:
    """The name a library was added under, found by comparing the listings around the add.

    **A name the listing before the add did not hold.** The server numbers a name already in use
    until it is unique (spec section 3.6), so the added library is always under a name the earlier
    listing lacked - however many libraries share its paths or its type, which is why paths and
    type are not what it is found by. Only another administrator adding a library between the two
    reads makes it more than one name; the candidates are then narrowed to the type sent, where
    that leaves any, and whatever remains is reported rather than guessed between (plan 6.7).
    """
    known = {row.name for row in before}
    added = [row for row in after if row.name not in known]
    if len(added) > 1 and kind is not None:
        same = [row for row in added if (row.collection_type or "").lower() == kind.lower()]
        if same:
            added = same
    return [row.name for row in added]


async def _add(
    args: argparse.Namespace,
    client: AdminClient,
    info: PublicInfo,
    password: Callable[[], str] | None,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    """`POST /Library/VirtualFolders` between two listings, and the name it ended up with."""
    await _sign_in_if_needed(args, client, info, password)
    before = await client.libraries()
    await client.add_library(args.name, args.kind, args.paths)
    names = settled_names(before, await client.libraries(), args.kind)
    if len(names) != 1:
        _write(
            stderr,
            f"{PROGRAM}: the library was added and its scan started, but the listing gained "
            f"{len(names)} libraries meanwhile, so which name is this one's cannot be told: "
            f"{', '.join(names) or 'none'}.",
        )
    for name in names:
        _write(stdout, name)
    return SUCCESS


async def _list(
    args: argparse.Namespace,
    client: AdminClient,
    info: PublicInfo,
    password: Callable[[], str] | None,
    stdout: TextIO,
) -> int:
    """`GET /Library/VirtualFolders`, one tab-separated line per library."""
    await _sign_in_if_needed(args, client, info, password)
    for row in await client.libraries():
        _write(stdout, "\t".join([row.name, row.collection_type or "-", *row.locations]))
    return SUCCESS


async def _scan(
    args: argparse.Namespace,
    client: AdminClient,
    password: Callable[[], str],
    stdout: TextIO,
) -> int:
    """`POST /Library/Refresh`, signed in, and not waited for (OQ-12)."""
    await client.sign_in(args.username, password())
    await client.refresh()
    _write(
        stdout,
        "A scan of every library was started. It is not waited for: browse the libraries from a "
        "client to see what it found.",
    )
    return SUCCESS


async def _dispatch(
    args: argparse.Namespace,
    stdin: TextIO,
    stdout: TextIO,
    stderr: TextIO,
    transport: httpx.AsyncBaseTransport | None,
) -> int:
    command = args.command if args.command == "setup" else f"library {args.library_command}"
    for path in getattr(args, "paths", None) or []:
        if "," in path:
            raise LocalRefusalError(
                f"{path!r} holds a comma, and the server reads its paths as one comma-separated "
                f"value, so it cannot be sent."
            )
    needs_password = command in ("setup", "library scan") or args.username is not None
    password = password_reader(args.password_stdin, stdin, stderr) if needs_password else None

    async with AdminClient(args.server, transport=transport) as client:
        info = await client.public_info()
        if command == "setup":
            assert password is not None  # noqa: S101 - needs_password is True for setup
            return await _setup(args, client, info, password, stdout)
        if command == "library add":
            return await _add(args, client, info, password, stdout, stderr)
        if command == "library list":
            return await _list(args, client, info, password, stdout)
        assert password is not None  # noqa: S101 - needs_password is True for scan
        return await _scan(args, client, password, stdout)


async def run(
    argv: Sequence[str],
    *,
    stdin: TextIO,
    stdout: TextIO,
    stderr: TextIO,
    transport: httpx.AsyncBaseTransport | None = None,
) -> int:
    """The whole program, with its streams and its transport handed in - the tests' seam."""
    try:
        with redirect_stdout(stdout), redirect_stderr(stderr):
            args = build_parser().parse_args(list(argv))
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else SUCCESS

    try:
        return await _dispatch(args, stdin, stdout, stderr, transport)
    except LocalRefusalError as exc:
        _write(stderr, f"{PROGRAM}: {exc}")
        return LOCALLY_REFUSED
    except Refused as exc:
        _write(stderr, f"{PROGRAM}: {exc.method} {exc.path} was refused: {exc.status} {exc.reason}")
        return SERVER_REFUSED
    except UnreachableError as exc:
        _write(stderr, f"{PROGRAM}: nothing answered at {args.server}: {exc}")
        return SERVER_REFUSED
    except UnexpectedAnswerError as exc:
        _write(stderr, f"{PROGRAM}: {args.server} does not answer as a Jellyfin server: {exc}")
        return SERVER_REFUSED


def main() -> None:
    """The `atrium-admin` script, and `python -m atrium.cli`."""
    sys.exit(asyncio.run(run(sys.argv[1:], stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr)))


__all__ = [
    "LOCALLY_REFUSED",
    "SERVER_REFUSED",
    "SUCCESS",
    "LocalRefusalError",
    "build_parser",
    "is_loopback_host",
    "main",
    "password_reader",
    "run",
    "settled_names",
]
