# SPDX-License-Identifier: GPL-3.0-or-later
"""Running `atrium-admin` against an application, and recording every request it makes.

**What the client sends is asserted from the wire, not from its source** (014 AC-9): the program
is run through `atrium.cli.commands.run` with its transport replaced by one that records each
request whole - method, address, headers and body - and then hands it to the application through
`httpx.ASGITransport` from the peer address the test names. The peer is required, as in
`tests/conformance/test_setup_window.py`, because the one rule the client's `setup` check mirrors
is decided by it.

The application is `tests/cli/conftest.py`'s `server`.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field

import httpx
from fastapi import FastAPI

from atrium.cli import commands

LOOPBACK = "127.0.0.1"
SERVER = "http://127.0.0.1:8096"

#: Spec section 3.8's operations - the four commands' own and the two borrowed from 001 and 002.
SECTION_3_8 = frozenset(
    {
        ("GET", "/System/Info/Public"),
        ("POST", "/Users/AuthenticateByName"),
        ("GET", "/Startup/User"),
        ("POST", "/Startup/User"),
        ("POST", "/Startup/Complete"),
        ("GET", "/Library/VirtualFolders"),
        ("POST", "/Library/VirtualFolders"),
        ("POST", "/Library/Refresh"),
    }
)

#: The two requests whose bodies carry a password by design (spec section 3.8): the first
#: account's update, and signing in.
CARRY_THE_PASSWORD = frozenset({("POST", "/Startup/User"), ("POST", "/Users/AuthenticateByName")})


@dataclass(frozen=True)
class Sent:
    """One request as it left the client, and what came back."""

    method: str
    path: str
    url: str
    headers: tuple[tuple[str, str], ...]
    body: bytes
    status: int
    answer: bytes

    @property
    def operation(self) -> tuple[str, str]:
        return (self.method, self.path)

    def header(self, name: str) -> str:
        (value,) = [value for key, value in self.headers if key.lower() == name.lower()]
        return value


class RecordingTransport(httpx.AsyncBaseTransport):
    """Every request recorded whole, then answered by the application from `peer`."""

    def __init__(self, app: FastAPI, peer: str) -> None:
        self._inner = httpx.ASGITransport(app=app, client=(peer, 51234))
        self.sent: list[Sent] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        body = await request.aread()
        response = await self._inner.handle_async_request(request)
        answer = await response.aread()
        self.sent.append(
            Sent(
                method=request.method,
                path=request.url.path,
                url=str(request.url),
                headers=tuple(
                    (key.decode("latin-1"), value.decode("latin-1"))
                    for key, value in request.headers.raw
                ),
                body=body,
                status=response.status_code,
                answer=answer,
            )
        )
        return response


class Terminal(io.StringIO):
    """Standard input that says it is a terminal."""

    def isatty(self) -> bool:
        return True


@dataclass
class Ran:
    """One invocation: its exit code, both output streams, and the requests it sent."""

    code: int
    stdout: str
    stderr: str
    sent: list[Sent] = field(default_factory=list)

    @property
    def operations(self) -> list[tuple[str, str]]:
        return [one.operation for one in self.sent]


async def invoke(
    transport: httpx.AsyncBaseTransport,
    *argv: str,
    stdin: io.StringIO | None = None,
) -> Ran:
    """Run the program once. `stdin` defaults to an empty stream that is not a terminal."""
    out, err = io.StringIO(), io.StringIO()
    before = len(transport.sent) if isinstance(transport, RecordingTransport) else 0
    code = await commands.run(
        list(argv),
        stdin=stdin if stdin is not None else io.StringIO(),
        stdout=out,
        stderr=err,
        transport=transport,
    )
    sent = transport.sent[before:] if isinstance(transport, RecordingTransport) else []
    return Ran(code=code, stdout=out.getvalue(), stderr=err.getvalue(), sent=sent)


def piped(password: str) -> io.StringIO:
    """A password written to standard input, as `--password-stdin` reads it."""
    return io.StringIO(f"{password}\n")
