#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared plumbing for the probe scripts.

A probe answers exactly one question about how a real Jellyfin behaves, prints its finding
together with the citation the documentation uses, and exits non-zero when the finding
contradicts what this repository currently claims. That last property is what makes the probes a
regression suite for the project's *beliefs* rather than only for its code: when a server upgrade
changes a behaviour, the probe says so instead of the documentation quietly becoming false.

The convention is specified in specs/010-conformance-harness/spec.md section 3.5.

Standard library only. These run before any environment is built.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ENV_FILE = ".env"
ENV_URL = "JELLYFIN_URL"
ENV_USERNAME = "JELLYFIN_USERNAME"
# These are the NAMES of environment variables, not secrets.
ENV_PASSWORD = "JELLYFIN_PASSWORD"  # noqa: S105
ENV_TOKEN = "JELLYFIN_TOKEN"  # noqa: S105

CLIENT = "atrium-probe"
DEVICE_ID = "atrium-probe-0000"
VERSION = "0.1"


class ProbeError(RuntimeError):
    """Something made the question unanswerable. Not a finding - an inability to look."""


# --------------------------------------------------------------------------------------------
# Local credentials
# --------------------------------------------------------------------------------------------


def load_env_file(start: Path | None = None) -> Path | None:
    """Read `.env` from the repository root into the environment, if it exists.

    Fifteen lines instead of a dependency, because a probe has to run before any environment is
    built. Real environment variables win over the file, which is what lets one probe be pointed
    at a different server without editing anything.

    Returns the path that was read, or None. Never logs a value.
    """
    here = start or Path(__file__).resolve().parent
    for directory in [here, *here.parents]:
        candidate = directory / ENV_FILE
        if not candidate.is_file():
            continue
        for raw in candidate.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip()
            if value[:1] == value[-1:] and value[:1] in {"'", '"'}:
                value = value[1:-1]
            os.environ.setdefault(key, value)
        return candidate
    return None


# --------------------------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------------------------


class Server:
    """A minimal client for the subset of the API the probes need."""

    def __init__(self, base_url: str, timeout: int = 30) -> None:
        self.base = base_url.rstrip("/")
        self.timeout = timeout
        self.token: str | None = None
        self.user_id: str | None = None
        self.version = "unknown"
        self.username_used: str | None = None
        # Kept so a probe can authenticate again on purpose - measuring how the server refuses a
        # request with correct credentials and a broken header needs correct credentials, and
        # sending wrong ones would count as a failed attempt against a real account. In memory
        # only: nothing prints it, and `Server` has no repr that could.
        self.password_used: str | None = None

    # -- request plumbing --------------------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        body: Any = None,
        extra_headers: dict[str, str] | None = None,
        raw: bool = False,
    ) -> Any:
        url = self.base + path
        if params:
            clean = {k: v for k, v in params.items() if v is not None}
            if clean:
                url += "?" + urllib.parse.urlencode(clean, doseq=True)

        headers = {"Accept": "application/json"}
        if self.token:
            headers["X-Emby-Token"] = self.token
        if extra_headers:
            headers.update(extra_headers)

        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"

        # S310: the URL is supplied by the operator running the probe against their own server.
        # Restricting the scheme here would stop a probe reaching a server on a custom port or
        # behind a proxy, which is the normal case rather than the exotic one.
        request = urllib.request.Request(url, data=data, headers=headers, method=method)  # noqa: S310
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310
                payload = response.read()
                if raw:
                    return response.status, dict(response.headers), payload
                if not payload:
                    return None
                return json.loads(payload)
        except urllib.error.HTTPError as exc:
            if raw:
                return exc.code, dict(exc.headers), exc.read()
            raise ProbeError(f"{method} {path} -> HTTP {exc.code}: {exc.read()[:200]!r}") from exc
        except urllib.error.URLError as exc:
            raise ProbeError(f"{method} {path} -> {exc.reason}") from exc

    def get(self, path: str, **params: Any) -> Any:
        return self._request("GET", path, params=params)

    def get_where(self, path: str, params: dict[str, Any]) -> Any:
        """GET with the query as a dict, for parameter names `get`'s own signature swallows.

        `get(path, **params)` cannot send a query parameter called `path` - Python binds it to the
        positional argument and raises. That is not hypothetical: /Environment/DirectoryContents,
        the only read-only view of the server's filesystem, takes exactly `path`. The same applies
        to `method`, `params`, `body`, `extra_headers` and `raw`.
        """
        return self._request("GET", path, params=params)

    def get_raw(self, path: str, **params: Any) -> tuple[int, dict[str, str], bytes]:
        return self._request("GET", path, params=params, raw=True)

    def post(self, path: str, body: Any = None, **params: Any) -> Any:
        return self._request("POST", path, params=params, body=body)

    def post_raw(self, path: str, body: Any = None, **params: Any) -> tuple[int, dict, bytes]:
        """POST returning (status, headers, payload) - for measuring the status itself.

        The parsed variant hides the difference between `200` and `204`, and a probe measuring
        which one a route answers cannot use a helper that swallows it.
        """
        return self._request("POST", path, params=params, body=body, raw=True)

    def delete(self, path: str, body: Any = None, **params: Any) -> Any:
        return self._request("DELETE", path, params=params, body=body)

    def delete_raw(self, path: str, body: Any = None, **params: Any) -> tuple[int, dict, bytes]:
        return self._request("DELETE", path, params=params, body=body, raw=True)

    # -- connection --------------------------------------------------------------------------

    def connect(self, username: str | None, password: str | None, token: str | None) -> None:
        info = self.get("/System/Info/Public")
        self.version = info.get("Version", "unknown")
        product = info.get("ProductName", "")
        if "jellyfin" not in product.lower():
            # Naming what was found, not only what was missing. A server that answers this route
            # at all is media-server-shaped, and the near miss is Emby - whose public info carries
            # no ProductName whatsoever, so the bare `ProductName=''` reads like a broken probe
            # rather than the right refusal. Jellyfin 10.11 answers ProductName="Jellyfin Server"
            # and a 10.x version.
            found = product or "no ProductName at all"
            raise ProbeError(
                f"the server at {self.base} reports {found}, ServerName="
                f"{info.get('ServerName', '?')!r}, Version={self.version!r}. The probes measure "
                "Jellyfin 10.11 (ADR-0004); pointing one at something else measures nothing and "
                "would file the answer under Jellyfin's name. A 4.x version with no ProductName "
                "is Emby, which is a different server with a different API."
            )

        if token:
            self.token = token
            me = self.get("/Users/Me")
            self.user_id = me["Id"]
            return

        if not username:
            raise ProbeError("no credentials: pass --username, or --token")

        result = self._request(
            "POST",
            "/Users/AuthenticateByName",
            body={"Username": username, "Pw": password or ""},
            extra_headers={
                "X-Emby-Authorization": (
                    f'MediaBrowser Client="{CLIENT}", Device="{CLIENT}", '
                    f'DeviceId="{DEVICE_ID}", Version="{VERSION}"'
                )
            },
        )
        self.token = result["AccessToken"]
        self.user_id = result["User"]["Id"]
        self.username_used = username
        self.password_used = password or ""


# --------------------------------------------------------------------------------------------
# The probe protocol
# --------------------------------------------------------------------------------------------


class Probe:
    """One question, its observations, its finding, and the verdict against the documentation.

    `expectation` is what this repository currently claims. Pass None when the documentation has
    only an open question: there is then nothing to contradict, and the probe reports its finding
    and names the section to fill in.
    """

    def __init__(
        self,
        script: str,
        question: str,
        document: str,
        section: str,
        expectation: str | None = None,
    ) -> None:
        self.script = script
        self.question = question
        self.document = document
        self.section = section
        self.expectation = expectation
        self.observations: list[tuple[str, str]] = []
        self.notes: list[str] = []
        self.finding: str | None = None
        self.matches: bool | None = None

    def observe(self, label: str, value: Any) -> None:
        self.observations.append((label, str(value)))

    def note(self, text: str) -> None:
        self.notes.append(text)

    def conclude(self, finding: str, matches_documentation: bool | None = None) -> None:
        self.finding = finding
        self.matches = matches_documentation

    def report(self, server: Server) -> int:
        # UTC rather than local: a citation carries a date that means the same thing
        # wherever it is read. timezone.utc rather than datetime.UTC for the 3.9 floor.
        today = datetime.now(timezone.utc).date().isoformat()
        width = max((len(label) for label, _ in self.observations), default=0)

        print()
        print(f"{self.script} - {self.question}")
        print()
        print(f"  server    {server.base}")
        print(f"  version   Jellyfin {server.version}")
        print(f"  date      {today}")
        print()
        for label, value in self.observations:
            print(f"  {label.ljust(width)}   {value}")
        if self.notes:
            print()
            for note in self.notes:
                for line in _wrap(note, 92):
                    print(f"  {line}")
        print()
        for line in _wrap(f"finding: {self.finding}", 92):
            print(f"  {line}")
        print()
        print(f"  [probe: tools/{self.script}, Jellyfin {server.version}, {today}]")
        print()

        if self.expectation is None:
            for line in _wrap(
                f"open question: {self.document} {self.section} has no claim to contradict. "
                f"Record the finding there and change the citation from prior-probe to probe.",
                92,
            ):
                print(f"  {line}")
            print()
            return 0

        if self.matches:
            print(f"  OK  documentation confirmed - {self.document} {self.section}")
            print()
            return 0

        print("  CONTRADICTION")
        for line in _wrap(f"{self.document} {self.section} claims: {self.expectation}", 88):
            print(f"    {line}")
        for line in _wrap(f"observed: {self.finding}", 88):
            print(f"    {line}")
        print()
        for line in _wrap(
            "Update that section. If this is a behaviour that changed rather than a claim "
            "that was always wrong, record it in docs/compatibility/behaviours.md with both "
            "dates - a claim that fails to reproduce is not deleted.",
            88,
        ):
            print(f"    {line}")
        print()
        return 1


def _wrap(text: str, width: int) -> list[str]:
    words, lines, current = text.split(), [], ""
    for word in words:
        if current and len(current) + 1 + len(word) > width:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}" if current else word
    if current:
        lines.append(current)
    return lines or [""]


# --------------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------------


def build_parser(
    description: str,
    needs_writes: bool = False,
    extra_arguments: Any = None,
) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=description, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "server",
        nargs="?",
        help=f"Base URL of a running Jellyfin, e.g. http://host:8096. Defaults to ${ENV_URL}",
    )
    parser.add_argument(
        "--username", "-u", help=f"User to authenticate as. Defaults to ${ENV_USERNAME}"
    )
    parser.add_argument(
        "--password",
        "-p",
        help=f"Discouraged: visible in the process list. Prefer ${ENV_PASSWORD} or the prompt",
    )
    parser.add_argument(
        "--token",
        help=f"Existing access token, instead of username and password. Defaults to ${ENV_TOKEN}",
    )
    parser.add_argument("--timeout", type=int, default=30)
    if needs_writes:
        parser.add_argument(
            "--allow-writes",
            action="store_true",
            help="Required: this probe cannot answer its question without writing to the server. "
            "It cleans up after itself, including on failure.",
        )
    if extra_arguments is not None:
        extra_arguments(parser)
    return parser


def connect(args: argparse.Namespace) -> Server:
    """Build a connected Server, resolving each credential from arguments then environment."""
    url = args.server or os.environ.get(ENV_URL)
    if not url:
        raise ProbeError(
            f"no server given: pass one as an argument, or set {ENV_URL} in {ENV_FILE}. "
            "Copy .env.example to .env to start"
        )

    username = args.username or os.environ.get(ENV_USERNAME)
    token = args.token or os.environ.get(ENV_TOKEN)
    password = args.password or os.environ.get(ENV_PASSWORD)
    if not token and username and not password:
        password = getpass.getpass(f"Password for {username}: ")

    server = Server(url, timeout=args.timeout)
    server.connect(username, password, token)
    return server


def main(
    run: Any,
    description: str,
    needs_writes: bool = False,
    extra_arguments: Any = None,
    with_args: bool = False,
) -> int:
    """Entry point shared by every probe: parse, connect, run, report, translate errors.

    `extra_arguments` adds a probe's own options to the parser; `with_args` hands the parsed
    namespace to `run` alongside the server. Both default off, so a probe that needs neither
    stays a one-line entry point.
    """
    env_file = load_env_file()
    parser = build_parser(description, needs_writes=needs_writes, extra_arguments=extra_arguments)
    args = parser.parse_args()

    if needs_writes and not args.allow_writes:
        print(
            "This probe writes to the server to answer its question, and cannot answer it any "
            "other way.\nIt creates only what it needs and removes it afterwards, including on "
            "failure.\nRe-run with --allow-writes to proceed.",
            file=sys.stderr,
        )
        return 2

    try:
        server = connect(args)
        if env_file:
            print(f"credentials from {env_file}", file=sys.stderr)
        probe = run(server, args) if with_args else run(server)
    except ProbeError as exc:
        print(f"cannot answer the question: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130

    return probe.report(server)
