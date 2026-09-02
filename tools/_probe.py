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
import contextlib
import getpass
import hashlib
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional, Tuple

ENV_FILE = ".env"
ENV_URL = "JELLYFIN_URL"
ENV_USERNAME = "JELLYFIN_USERNAME"
# These are the NAMES of environment variables, not secrets.
ENV_PASSWORD = "JELLYFIN_PASSWORD"  # noqa: S105
ENV_TOKEN = "JELLYFIN_TOKEN"  # noqa: S105

CLIENT = "atrium-probe"
#: The **base** of a device id, not a device id. Every account a run signs in as gets one of its
#: own, derived below: the reference binds a token to a device, so two accounts sharing one device
#: are one session and the second sign-in revokes the first's token
#: `[probe: tools/differential.py --named, Jellyfin 10.11.11, 2026-09-02]`. A probe that held an
#: administrator's token while signing in as a throwaway user therefore lost the token it needed
#: to clean up with, which is why the register below reports a `401` as its own failure class.
DEVICE_ID = "atrium-probe-0000"
VERSION = "0.1"


def device_for(account: str) -> str:
    """The device id one account signs in from. Distinct accounts, distinct devices.

    Derived rather than allocated so that re-running a probe reuses the same session row instead
    of leaving one behind per run, and so that two `Server` objects for the same account in one
    process are one session on purpose rather than by accident.
    """
    return DEVICE_ID + "-" + hashlib.sha256(account.encode("utf-8")).hexdigest()[:12]


class ProbeError(RuntimeError):
    """Something made the question unanswerable. Not a finding - an inability to look.

    `status` is the HTTP status when the server answered one, and `transport` is True when it
    never answered at all. Both exist because the teardown below has to tell a probe that forgot
    to clean up from a probe that was locked out or whose server died mid-run, and reading that
    off a formatted message would be a parser of our own prose.
    """

    def __init__(self, message: str, status: Optional[int] = None, transport: bool = False) -> None:
        super().__init__(message)
        self.status = status
        self.transport = transport


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
# What a run created on somebody's server, and what removes it
# --------------------------------------------------------------------------------------------

#: Why an object this run created is still on the server after the teardown ran. Only the first
#: is the probe's own defect; the other three exist so that the enforcement does not cry wolf.
LEAKED = "leaked"
REVOKED = "the token was revoked"
UNREACHABLE = "the server stopped answering"
ALREADY_GONE = "already removed"


class Creation:
    """A route that creates something outliving the request, and the route that removes it.

    Two entries, and they are the two that have actually been left behind: 009's probe runs left
    **28 playlists** on an operator's server on 2026-09-01 (010 spec section 3.5), and the seats a
    run signs in as are the accounts 010 T7 and T12 measured a revoked token failing to delete.
    Matched on the exact path a probe writes, because both are literal constants in every one of
    them - a pattern would be a guess about paths nobody sends.
    """

    def __init__(self, post: str, removal: str, what: str) -> None:
        self.post = post
        self.removal = removal
        self.what = what


CREATES: Tuple[Creation, ...] = (
    Creation(post="/Playlists", removal="/Items/{id}", what="playlist"),
    Creation(post="/Users/New", removal="/Users/{id}", what="user account"),
)


class Owned:
    """One thing this run created, the server it lives on, and the request that removes it."""

    def __init__(self, server: Any, removal: str, what: str) -> None:
        self.server = server
        self.removal = removal
        self.what = what

    def __str__(self) -> str:
        return f"{self.what} at {self.server.base}{self.removal}"


class Outstanding:
    """An owned object the teardown could not remove, and which of the four reasons it was."""

    def __init__(self, owned: Owned, reason: str, detail: str) -> None:
        self.owned = owned
        self.reason = reason
        self.detail = detail


class Register:
    """*"A probe that writes creates what it needs and removes it, including on failure"* - as a
    mechanism rather than as a sentence (010 spec section 3.5).

    That sentence was checked against a real server on 2026-09-01 and did not hold:
    `tools/README.md` said every writing probe deletes what it made including on failure, and 28
    playlists were sitting on the server carrying the names those probes create them under. The
    sentence was true of the code each script had written for itself and false of the set, which
    is what a shared register fixes: **`Server` records a creation as it happens**, so a probe
    does not have to remember, and `main` tears the register down in a `finally`, so an exception
    on any path out still removes what the run made.

    A probe that removes its own creation leaves nothing here: the removal request de-registers
    it, so the two mechanisms do not fight and a double delete cannot happen.

    Process-wide rather than per-`Server`, because the thing that leaks is usually the *second*
    connection - a throwaway seat signed in beside the administrator - and a register hanging off
    the `Server` a probe happened to return would never see it.
    """

    def __init__(self) -> None:
        self._owned: List[Owned] = []
        self.removed = 0

    def __len__(self) -> int:
        return len(self._owned)

    def clear(self) -> None:
        self._owned = []
        self.removed = 0

    def own(self, server: Any, removal: str, what: str) -> None:
        if any(item.server is server and item.removal == removal for item in self._owned):
            return
        self._owned.append(Owned(server, removal, what))

    def disown(self, server: Any, removal: str) -> None:
        """Forget an object the probe removed itself. Called by the removal request, not by hand."""
        self._owned = [
            item for item in self._owned if not (item.server is server and item.removal == removal)
        ]

    def note(self, server: Any, method: str, path: str, payload: Any) -> None:
        """Record what a request just created, or forget what it just removed.

        `payload` is whatever the server answered, parsed where it could be. A creation is only
        recorded when the server actually returned an identifier: a refused `POST /Playlists`
        creates nothing, and registering an object that does not exist would make the teardown
        report a leak on every probe that measures a refusal.
        """
        if method == "DELETE":
            self.disown(server, path)
            return
        if method != "POST":
            return
        for creation in CREATES:
            if path != creation.post:
                continue
            identifier = _identifier_in(payload)
            if identifier:
                self.own(server, creation.removal.format(id=identifier), creation.what)
            return

    def teardown(self) -> List[Outstanding]:
        """Remove everything still owned, newest first, and say what could not be removed.

        Newest first because a run creates a seat and then a playlist inside it, and removing the
        account first would take the token the playlist has to be removed with.

        Every removal is attempted even when an earlier one failed: one dead object must not take
        the rest of the cleanup with it, which is the failure mode the `finally` in each of the
        probes could not cover either.
        """
        outstanding: List[Outstanding] = []
        for item in reversed(self._owned):
            try:
                item.server.delete(item.removal)
                self.removed += 1
            except ProbeError as failure:
                outstanding.append(Outstanding(item, _why(failure), str(failure)))
            except Exception as failure:  # a teardown reports, it never raises
                outstanding.append(Outstanding(item, LEAKED, repr(failure)))
        self._owned = []
        return outstanding


def _identifier_in(payload: Any) -> str:
    """The `Id` a creating route answers with, whether the caller asked for bytes or for JSON."""
    if isinstance(payload, (bytes, bytearray)):
        try:
            payload = json.loads(payload)
        except (ValueError, TypeError):
            return ""
    if isinstance(payload, dict):
        return str(payload.get("Id") or "")
    return ""


def _why(failure: ProbeError) -> str:
    """Which of the four reasons a removal did not happen.

    **Two of them are measured and neither is a probe forgetting to clean up** (010 T12): the
    reference binds a token to a device, so a second sign-in on one device revokes the first
    token and every `DELETE` after it answers `401`; and the single-use instance of ADR-0007 dies
    with `SIGILL` often enough to have been measured - four of eight starts on 2026-09-02, plan
    section 7 - after which every request is a connection refused. Reporting either as a leak is
    how an enforcement stops being read.
    """
    if failure.transport:
        return UNREACHABLE
    if failure.status in (401, 403):
        return REVOKED
    if failure.status == 404:
        return ALREADY_GONE
    return LEAKED


#: The register `main` tears down. One per process, and a probe never constructs its own.
OWNED = Register()


# --------------------------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------------------------


class Server:
    """A minimal client for the subset of the API the probes need."""

    def __init__(self, base_url: str, timeout: int = 30, device_id: str | None = None) -> None:
        self.base = base_url.rstrip("/")
        self.timeout = timeout
        self.token: str | None = None
        self.user_id: str | None = None
        self.version = "unknown"
        # The device this connection signs in from. `connect` derives it from the account unless
        # the caller named one, because a device is per account and not per process: two accounts
        # on one device are one session on the reference, and the second sign-in revokes the
        # first's token. A probe that needs to name its own session in a query reads this rather
        # than the module constant, which is the base and not an id.
        self.device_id = device_id or DEVICE_ID
        self._device_id_given = device_id is not None
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
        raw_body: bytes | None = None,
        send_token: bool = True,
    ) -> Any:
        url = self.base + path
        if params:
            clean = {k: v for k, v in params.items() if v is not None}
            if clean:
                url += "?" + urllib.parse.urlencode(clean, doseq=True)

        headers = {"Accept": "application/json"}
        if self.token and send_token:
            headers["X-Emby-Token"] = self.token
        if extra_headers:
            headers.update(extra_headers)

        data = None
        if raw_body is not None:
            # Bytes exactly as given, so a probe can measure what a *malformed* body answers.
            # `json.dumps` would turn "{not json" into the valid JSON string '"{not json"', which
            # binds differently and would measure a different refusal than the one asked about.
            data = raw_body
            headers["Content-Type"] = "application/json"
        elif body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"

        # S310: the URL is supplied by the operator running the probe against their own server.
        # Restricting the scheme here would stop a probe reaching a server on a custom port or
        # behind a proxy, which is the normal case rather than the exotic one.
        request = urllib.request.Request(url, data=data, headers=headers, method=method)  # noqa: S310
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310
                payload = response.read()
                OWNED.note(self, method, path, payload)
                if raw:
                    return response.status, dict(response.headers), payload
                if not payload:
                    return None
                return json.loads(payload)
        except urllib.error.HTTPError as exc:
            if raw:
                return exc.code, dict(exc.headers), exc.read()
            raise ProbeError(
                f"{method} {path} -> HTTP {exc.code}: {exc.read()[:200]!r}", status=exc.code
            ) from exc
        except urllib.error.URLError as exc:
            raise ProbeError(f"{method} {path} -> {exc.reason}", transport=True) from exc

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

    def post_raw(
        self, path: str, body: Any = None, raw_body: bytes | None = None, **params: Any
    ) -> tuple[int, dict, bytes]:
        """POST returning (status, headers, payload) - for measuring the status itself.

        The parsed variant hides the difference between `200` and `204`, and a probe measuring
        which one a route answers cannot use a helper that swallows it. `raw_body` sends bytes
        verbatim, which is the only way to ask what an unparseable body answers.
        """
        return self._request("POST", path, params=params, body=body, raw=True, raw_body=raw_body)

    def get_streaming(
        self,
        path_and_query: str,
        max_bytes: int,
        extra_headers: dict[str, str] | None = None,
        send_token: bool = True,
    ) -> tuple[int, dict[str, str], bytes]:
        """GET reading at most `max_bytes` of the body, then closing the connection.

        The delivery probes ask header-sized questions - does this response carry a
        `Content-Length`, does this body start with the right magic bytes - about responses whose
        full body is a film. Reading it all to answer would download gigabytes and keep the
        server encoding for the whole read; closing early is also, deliberately, the same signal
        a disconnecting client sends, which the reference answers by stopping the work.

        `send_token=False` sends nothing at all, which is the only way to ask whether a delivery
        route *requires* a credential - and behaviours section 2.10 says the answer is not the
        obvious one.

        Returns (status, headers, first bytes). Error responses come back the same way.
        """
        url = self.base + path_and_query
        headers = {}
        if self.token and send_token:
            headers["X-Emby-Token"] = self.token
        if extra_headers:
            headers.update(extra_headers)
        request = urllib.request.Request(url, headers=headers, method="GET")  # noqa: S310
        try:
            response = urllib.request.urlopen(request, timeout=self.timeout)  # noqa: S310
        except urllib.error.HTTPError as exc:
            payload = exc.read()[:max_bytes]
            exc.close()
            return exc.code, dict(exc.headers), payload
        except urllib.error.URLError as exc:
            raise ProbeError(
                f"GET {path_and_query.split('?')[0]} -> {exc.reason}", transport=True
            ) from exc
        try:
            payload = response.read(max_bytes)
        finally:
            response.close()
        return response.status, dict(response.headers), payload

    def delete(self, path: str, body: Any = None, **params: Any) -> Any:
        return self._request("DELETE", path, params=params, body=body)

    def delete_raw(
        self, path: str, body: Any = None, send_token: bool = True, **params: Any
    ) -> tuple[int, dict, bytes]:
        """DELETE returning (status, headers, payload).

        `send_token=False` sends no credential at all, which is `get_streaming`'s rule for the
        same reason: whether a route *requires* a token is a question about the route, and 008
        has already found the answer to be the surprising one twice.
        """
        return self._request(
            "DELETE", path, params=params, body=body, raw=True, send_token=send_token
        )

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

        if not self._device_id_given:
            self.device_id = device_for(username)
        result = self._request(
            "POST",
            "/Users/AuthenticateByName",
            body={"Username": username, "Pw": password or ""},
            extra_headers={
                "X-Emby-Authorization": (
                    f'MediaBrowser Client="{CLIENT}", Device="{CLIENT}", '
                    f'DeviceId="{self.device_id}", Version="{VERSION}"'
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


@contextlib.contextmanager
def _connection(args: argparse.Namespace, connect_with: Any, env_file: Path | None) -> Any:
    """The server a probe measures, for as long as the probe needs it.

    The ordinary case is one connection to a server somebody else is running, and nothing has to
    be torn down. `connect_with` is the other one, and it exists because of what it has to
    guarantee: a probe that *makes* its own server must destroy it after the report, on every
    path out, and a report printed after the teardown would print the version of a server that no
    longer exists.
    """
    if connect_with is not None:
        with connect_with(args) as server:
            yield server
        return
    server = connect(args)
    if env_file:
        print(f"credentials from {env_file}", file=sys.stderr)
    yield server


#: What a run exits with when it left something behind that it should have removed. Distinct from
#: `1`, which is a **finding** contradicting the documentation (AC-7), and from `2`, which is an
#: inability to look: a leak is neither a measurement nor a broken connection, and a reader who
#: cannot tell them apart has to read the output to find out which happened.
CLEANUP_FAILED = 3


def report_cleanup(outstanding: List[Outstanding], removed: int) -> bool:
    """Say what the register removed and what it could not, and answer whether that is a leak.

    **Only `LEAKED` is a leak.** A `401` means the token was revoked out from under the run and a
    connection refused means the server is not there any more; both were measured on 2026-09-02
    (010 T12) and neither is the probe forgetting to clean up. Reporting them as leaks is how an
    enforcement gets ignored, and an ignored enforcement is worse than none - which is spec
    section 6's *"does not cry wolf"* applied to the teardown rather than to the comparison.

    An object the register removed is **reported and not failed**: the contract is about what is
    left on the server, and the server is clean either way. The line exists so that a probe
    relying on the shared teardown is visible rather than silent.
    """
    if removed:
        print(
            f"cleanup: the shared register removed {removed} object(s) the probe had not removed "
            f"itself. That is the contract holding, not a failure - but a probe that leaves its "
            f"own creations to the register is one whose own teardown is worth a look.",
            file=sys.stderr,
        )
    if not outstanding:
        return False
    leaked = [item for item in outstanding if item.reason == LEAKED]
    for item in outstanding:
        print(f"cleanup: {item.owned} was not removed - {item.reason}", file=sys.stderr)
        print(f"         {item.detail}", file=sys.stderr)
    if not leaked:
        print(
            "cleanup: none of the above is this probe forgetting to clean up. A revoked token and "
            "a server that stopped answering are the two failure modes measured on 2026-09-02, "
            "and the run's exit code is its finding rather than this.",
            file=sys.stderr,
        )
        return False
    print(
        f"cleanup: {len(leaked)} object(s) this run created are still on the server, and nothing "
        f"explains it. 010 spec section 3.5: a probe that writes creates what it needs and "
        f"removes it, including on failure - so a probe that leaks is a probe with a defect. "
        f"Remove them by hand and fix the probe.",
        file=sys.stderr,
    )
    return True


def main(
    run: Any,
    description: str,
    needs_writes: bool = False,
    extra_arguments: Any = None,
    with_args: bool = False,
    connect_with: Any = None,
) -> int:
    """Entry point shared by every probe: parse, connect, run, report, translate errors.

    `extra_arguments` adds a probe's own options to the parser; `with_args` hands the parsed
    namespace to `run` alongside the server. Both default off, so a probe that needs neither
    stays a one-line entry point.

    `connect_with` replaces *"connect to the server the environment names"* with a probe's own
    context manager, and exactly one probe needs it: `probe_reference_scan.py` measures a server
    that does not exist until it stands one up, and must destroy it afterwards whatever happened
    (010 spec section 3.1). It is a parameter rather than a second entry point so that every probe
    still reaches this function — the citation, the contradiction and the exit code are the
    convention, and a probe that printed its own would be outside it.
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
        with _connection(args, connect_with, env_file) as server:
            # The teardown is a `finally` and not a line after the report, which is the whole
            # difference between the contract and the claim: an exception on any path out of
            # `run` still removes what the run created. Inside the `with`, because a probe that
            # made its own server destroys it on the way out of that block and a removal issued
            # afterwards would be issued at nothing.
            try:
                probe = run(server, args) if with_args else run(server)
                code = probe.report(server)
            finally:
                leaked = report_cleanup(OWNED.teardown(), OWNED.removed)
            return CLEANUP_FAILED if leaked else code
    except ProbeError as exc:
        print(f"cannot answer the question: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130
