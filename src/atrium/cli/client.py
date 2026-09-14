# SPDX-License-Identifier: GPL-3.0-or-later
"""The HTTP half of `atrium-admin`: one method per operation 014 spec section 3.8 names.

**Eight operations and no ninth.** `GET /System/Info/Public` (001) and `POST
/Users/AuthenticateByName` (002), then the six of 014 sections 3.2 to 3.7. Nothing here reads a
file, a database or an environment variable, and nothing is imported from the server: what this
client knows about the server it learns over the wire, as any other client does.

**One device, whatever the invocation.** Every request carries the `MediaBrowser` client header
with the fixed `DeviceId` `atrium-admin-<host name>`, so signing in again from the same machine
replaces this client's previous token rather than adding a session beside it (002: signing in
from a device revokes that device's token). No token outlives the process (OQ-9).

**A refusal is reported with the reason the server gave**, in whichever of the reference's
shapes it arrived: problem details carry a `title` (and, for a validation failure, an `errors`
map), a controller's own message is a JSON-encoded bare string, a controller refusal is
`text/plain`, and the `401` and `403` carry nothing - for those the status line's reason is all
there is.

See specs/014-first-time-setup/plan.md sections 5 and 6.7.
"""

from __future__ import annotations

import json
import socket
from collections.abc import Sequence
from dataclasses import dataclass
from importlib import metadata
from typing import Any, Final

import httpx

#: What this client calls itself in the client header.
CLIENT_NAME: Final = "atrium-admin"

#: The distribution this program ships in, read for the header's `Version` only.
DISTRIBUTION: Final = "atrium-media-server"

#: Long enough for a server busy with a scan to answer a write (plan section 9's first row), and
#: bounded so a server that stopped answering is reported rather than waited on for ever.
TIMEOUT_SECONDS: Final = 30.0


@dataclass(frozen=True)
class PublicInfo:
    """The two properties of `GET /System/Info/Public` this client reads."""

    product_name: str
    startup_wizard_completed: bool


@dataclass(frozen=True)
class LibraryRow:
    """One row of `GET /Library/VirtualFolders`, as far as this client prints it."""

    name: str
    collection_type: str | None
    locations: tuple[str, ...]


class Refused(Exception):  # noqa: N818 - plan section 5's name for it
    """The server answered an operation with a status that is not its success."""

    def __init__(self, method: str, path: str, status: int, reason: str) -> None:
        super().__init__(f"{method} {path}: {status} {reason}")
        self.method = method
        self.path = path
        self.status = status
        self.reason = reason


class UnreachableError(Exception):
    """Nothing answered at the address, or the connection failed on the way."""


class UnexpectedAnswerError(Exception):
    """Something answered, and not as a Jellyfin server answers: a success whose body is not the
    shape the operation declares - including a `/System/Info/Public` with no `ProductName`."""


def device_id(host_name: str | None = None) -> str:
    """`atrium-admin-<host name>` - the same for every invocation on one machine (plan 6.7)."""
    return f"{CLIENT_NAME}-{host_name if host_name is not None else socket.gethostname()}"


def _version() -> str:
    try:
        return metadata.version(DISTRIBUTION)
    except metadata.PackageNotFoundError:
        return "0"


def _quoted(value: str) -> str:
    """A header component's value. The grammar has no escape for `"`, so one is dropped."""
    return value.replace('"', "")


def reason_of(response: httpx.Response) -> str:
    """The reason a refusal gave, in the shape it gave it (behaviours section 1.11)."""
    media_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
    if response.content:
        if media_type.endswith("json"):
            try:
                parsed: Any = json.loads(response.content)
            except ValueError:
                parsed = None
            if isinstance(parsed, str) and parsed.strip():
                return parsed
            if isinstance(parsed, dict) and isinstance(parsed.get("title"), str):
                return _with_errors(parsed["title"], parsed.get("errors"))
        elif media_type.startswith("text/"):
            text = response.text.strip()
            if text:
                return text.splitlines()[0]
    return response.reason_phrase or "(no reason given)"


def _with_errors(title: str, errors: object) -> str:
    """A validation title followed by what it names - `name: The name field is required.`"""
    if not isinstance(errors, dict) or not errors:
        return title
    named = [
        f"{key}: {message}"
        for key, messages in errors.items()
        for message in (messages if isinstance(messages, list) else [messages])
    ]
    return f"{title} {'; '.join(named)}"


class AdminClient:
    """One server, one process's worth of requests, and at most one token."""

    def __init__(
        self,
        base_url: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        host_name: str | None = None,
    ) -> None:
        name = host_name if host_name is not None else socket.gethostname()
        self._identity = (
            f'MediaBrowser Client="{CLIENT_NAME}", Device="{_quoted(name)}", '
            f'DeviceId="{_quoted(device_id(name))}", Version="{_quoted(_version())}"'
        )
        self._token: str | None = None
        self._http = httpx.AsyncClient(
            base_url=base_url, transport=transport, timeout=TIMEOUT_SECONDS
        )

    async def __aenter__(self) -> AdminClient:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self._http.aclose()

    # -- the wire ------------------------------------------------------------------------------

    def _authorization(self) -> str:
        if self._token is None:
            return self._identity
        return f'{self._identity}, Token="{self._token}"'

    async def _send(
        self,
        method: str,
        path: str,
        *,
        expect: int,
        json_body: object = None,
        params: dict[str, str] | None = None,
    ) -> httpx.Response:
        try:
            response = await self._http.request(
                method,
                path,
                json=json_body,
                params=params,
                headers={"Authorization": self._authorization()},
            )
        except httpx.HTTPError as exc:
            raise UnreachableError(f"{type(exc).__name__}: {exc}") from exc
        if response.status_code != expect:
            raise Refused(method, path, response.status_code, reason_of(response))
        return response

    @staticmethod
    def _json(response: httpx.Response, path: str) -> Any:
        try:
            return response.json()
        except ValueError as exc:
            raise UnexpectedAnswerError(f"{path} answered a body that is not JSON") from exc

    # -- the operations ------------------------------------------------------------------------

    async def public_info(self) -> PublicInfo:
        """`GET /System/Info/Public` (001) - what is answering, and whether setup is finished."""
        path = "/System/Info/Public"
        body = self._json(await self._send("GET", path, expect=200), path)
        product = body.get("ProductName") if isinstance(body, dict) else None
        if not isinstance(product, str) or not product:
            raise UnexpectedAnswerError(f"{path} answered with no ProductName")
        completed = body.get("StartupWizardCompleted")
        if not isinstance(completed, bool):
            raise UnexpectedAnswerError(f"{path} answered with no StartupWizardCompleted")
        return PublicInfo(product_name=product, startup_wizard_completed=completed)

    async def sign_in(self, username: str, password: str) -> None:
        """`POST /Users/AuthenticateByName` (002). The token lives in this object only."""
        path = "/Users/AuthenticateByName"
        answered = await self._send(
            "POST", path, expect=200, json_body={"Username": username, "Pw": password}
        )
        body = self._json(answered, path)
        token = body.get("AccessToken") if isinstance(body, dict) else None
        if not isinstance(token, str) or not token:
            raise UnexpectedAnswerError(f"{path} answered with no AccessToken")
        self._token = token

    async def first_user(self) -> str:
        """`GET /Startup/User` - the first account's name, created if there is none (3.2)."""
        path = "/Startup/User"
        body = self._json(await self._send("GET", path, expect=200), path)
        name = body.get("Name") if isinstance(body, dict) else None
        if not isinstance(name, str):
            raise UnexpectedAnswerError(f"{path} answered with no Name")
        return name

    async def update_first_user(self, name: str, password: str) -> None:
        """`POST /Startup/User` - the first account renamed if asked, and given its password."""
        await self._send(
            "POST", "/Startup/User", expect=204, json_body={"Name": name, "Password": password}
        )

    async def complete(self) -> None:
        """`POST /Startup/Complete` - the setup window closed (3.4)."""
        await self._send("POST", "/Startup/Complete", expect=204)

    async def add_library(self, name: str, kind: str | None, paths: Sequence[str]) -> None:
        """`POST /Library/VirtualFolders`, with a scan asked for (plan section 6.7): during setup
        it is the only way to start one, because `POST /Library/Refresh` needs an administrator.

        `paths` is one comma-separated value, so a path holding a comma cannot be sent in it; the
        caller refuses one before this is reached.
        """
        params = {"name": name, "paths": ",".join(paths), "refreshLibrary": "true"}
        if kind is not None:
            params["collectionType"] = kind
        await self._send("POST", "/Library/VirtualFolders", expect=204, params=params)

    async def libraries(self) -> list[LibraryRow]:
        """`GET /Library/VirtualFolders` - every library (3.5)."""
        path = "/Library/VirtualFolders"
        body = self._json(await self._send("GET", path, expect=200), path)
        if not isinstance(body, list):
            raise UnexpectedAnswerError(f"{path} answered something that is not a list")
        rows = []
        for entry in body:
            name = entry.get("Name") if isinstance(entry, dict) else None
            if not isinstance(name, str):
                raise UnexpectedAnswerError(f"{path} answered a row with no Name")
            kind = entry.get("CollectionType")
            locations = entry.get("Locations") or []
            rows.append(
                LibraryRow(
                    name=name,
                    collection_type=kind if isinstance(kind, str) else None,
                    locations=tuple(str(one) for one in locations),
                )
            )
        return rows

    async def refresh(self) -> None:
        """`POST /Library/Refresh` - a scan of every library started, and not waited for (3.7)."""
        await self._send("POST", "/Library/Refresh", expect=204)


__all__ = [
    "CLIENT_NAME",
    "AdminClient",
    "LibraryRow",
    "PublicInfo",
    "Refused",
    "UnexpectedAnswerError",
    "UnreachableError",
    "device_id",
    "reason_of",
]
