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
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

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

#: Seconds a playlist must sit between the last write to it and its deletion.
#:
#: The reference answers an entry write before it has finished with the playlist: creation with
#: a non-empty `Ids`, the add route and the remove route all queue a metadata refresh onto a
#: background queue [source: Emby.Server.Implementations/Playlists/PlaylistManager.cs:252, :280
#: @ v10.11.11], and so does `POST /Playlists/{id}` with `Ids`, which goes through the same add
#: [source: Emby.Server.Implementations/Playlists/PlaylistManager.cs:593-602 @ v10.11.11]. A
#: refresh that runs after the playlist has been deleted writes its folder and playlist.xml back
#: out: the row stays deleted, the folder does not, and the next library scan turns that folder
#: into a playlist again. Measured against 10.11.11 on 2026-09-01: the folder came back 0.9s after
#: a delete that followed the creation immediately, and nothing came back when the delete waited
#: three seconds. That is one of the two ways the 28 leaked playlists were left.
PLAYLIST_SETTLE = 3.0

#: Seconds after the last playlist deletion before the teardown looks for its folder on disk.
#:
#: The folder comes back 0.9s after the delete when it comes back at all (measured 2026-09-01,
#: above), so looking straight away would only ever confirm the answer the delete already gave.
FOLDER_LOOK = 1.5

#: What the register calls a playlist it found rather than was told about. See `Server._request`.
STRAY = "playlist a refused creation left behind"


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

    def __init__(self, server: Any, removal: str, what: str, stray: bool = False) -> None:
        self.server = server
        self.removal = removal
        self.what = what
        #: True for a playlist a refused `POST /Playlists` made anyway: no probe was ever told its
        #: id, so no probe's own teardown could have removed it.
        self.stray = stray

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

    **Two defects measured on 2026-09-01 were not in any cleanup list**, and the register holds
    what fixes them rather than a second mechanism beside it:

    * *a refusal can have created the playlist* - so a refused `POST /Playlists` is followed by a
      look for a playlist of that name that was not there before the request, and what the look
      finds is owned here as a stray (`Server._request`, `STRAY`);
    * *a deletion that follows a write too closely leaves the folder on disk* - so the register
      keeps the time of the last write to every playlist this run created or wrote to, and every
      `DELETE /Items/{id}` on one of them waits out `PLAYLIST_SETTLE` first (`settle`). After the
      teardown it looks on the server's disk for the folders of the playlists it saw deleted, and
      reports any that are still there (`leftover_folders`).

    The clock and the sleep are attributes so that a test can drive both without waiting.
    """

    def __init__(self) -> None:
        self.clear()

    def __len__(self) -> int:
        return len(self._owned)

    def clear(self) -> None:
        self._owned: List[Owned] = []
        self.removed = 0
        #: How many of `removed` were strays, which no probe could have removed itself.
        self.strays_removed = 0
        #: Playlist key -> when this run last wrote to it, on the register's clock.
        self._written: Dict[str, float] = {}
        #: Playlist key -> (the connection that can read it, where its folder is on the server).
        self._paths: Dict[str, Tuple[Any, str]] = {}
        #: The folders of playlists this run saw deleted, still to be looked for on disk.
        self._deleted: List[Tuple[Any, str]] = []
        self._last_deletion: Optional[float] = None
        #: How long, in total, deletions waited for a playlist to settle, and how many of them did.
        self.settled = 0.0
        self.settles = 0
        self.clock: Callable[[], float] = time.monotonic
        self.sleep: Callable[[float], None] = time.sleep

    def own(self, server: Any, removal: str, what: str, stray: bool = False) -> None:
        if any(item.server is server and item.removal == removal for item in self._owned):
            return
        self._owned.append(Owned(server, removal, what, stray))

    # -- the settle clock ------------------------------------------------------------------------

    def written(self, method: str, path: str) -> None:
        """Start the settle clock for a write to `/Playlists/{id}` or below, whatever it answered.

        Whatever it answered, because a write that is refused can still have written: the
        refusals 009 measures are raised from inside the reference's own playlist manager, after
        the row has been updated. Every write method and not only the two that queue a refresh,
        because a wait of three seconds is cheaper than a second measurement of which routes do.
        """
        if method not in ("POST", "DELETE", "PUT", "PATCH"):
            return
        parts = path.split("/")
        if len(parts) >= 3 and parts[1] == "Playlists" and parts[2]:
            self.stamp(parts[2])

    def stamp(self, playlist_id: Any) -> None:
        self._written[_playlist_key(playlist_id)] = self.clock()

    def settle(self, method: str, path: str) -> None:
        """Before `DELETE /Items/{id}` on a playlist this run wrote to, wait out `PLAYLIST_SETTLE`.

        **Every such deletion waits, including one that is the measurement**, and that is a
        decision rather than an oversight. `probe_item_deletion.py`, `probe_playlist_shares.py`
        and `probe_playlist_visibility.py` delete a playlist they have just created with entries,
        and observe the status, the headers, the bytes and whether the item is there afterwards.
        None of the four depends on how long ago the playlist was written: who may delete is
        decided by the owner, the shares and the account's policy, all set when the playlist was
        created. What does depend on it is the folder - an immediate deletion of a playlist
        created with entries is exactly the leak this constant describes, so exempting the
        measured deletions would leave the defect in the probe that deletes the most. The wait is
        not silent: the teardown reports how long deletions waited, and how many.

        Keyed on the identifier however it is spelled, because one probe deletes with the dashed
        spelling on purpose.
        """
        if method != "DELETE":
            return
        parts = path.split("/")
        if len(parts) != 3 or parts[1] != "Items":
            return
        written = self._written.get(_playlist_key(parts[2]))
        if written is None:
            return
        remaining = PLAYLIST_SETTLE - (self.clock() - written)
        if remaining > 0:
            self.sleep(remaining)
            self.settled += remaining
            self.settles += 1

    # -- where the folders are -------------------------------------------------------------------

    def remember(self, server: Any, playlist_id: Any, folder: str) -> None:
        """Where a playlist this run created lives on the server's disk, read at creation time."""
        if folder:
            self._paths[_playlist_key(playlist_id)] = (server, folder)

    def leftover_folders(self) -> List[str]:
        """Which folders of the playlists this run saw deleted are still on the server's disk.

        **Best effort, and never a failure.** Read through `/Environment/DirectoryContents`, which
        only an administrator may ask, so a run whose connections are not administrators gets an
        empty answer rather than a wrong one - and a folder it could not look for is not reported,
        because a leak nobody measured is not a finding.
        """
        deleted, self._deleted = self._deleted, []
        if not deleted:
            return []
        if self._last_deletion is not None:
            remaining = FOLDER_LOOK - (self.clock() - self._last_deletion)
            if remaining > 0:
                self.sleep(remaining)
        wanted: Dict[str, Set[str]] = {}
        readers: List[Any] = []
        for server, folder in deleted:
            cut = max(folder.rfind("/"), folder.rfind("\\"))
            if cut > 0 and folder[cut + 1 :]:
                wanted.setdefault(folder[: cut + 1], set()).add(folder[cut + 1 :])
            if all(server is not seen for seen in readers):
                readers.append(server)
        left: List[str] = []
        for parent, names in wanted.items():
            for reader in readers:
                rows = _directory(reader, parent.rstrip("/\\") or parent)
                if rows is None:
                    continue
                left.extend(
                    parent + str(row.get("Name"))
                    for row in rows
                    if isinstance(row, dict) and row.get("Name") in names
                )
                break
        return sorted(left)

    def disown(self, server: Any, removal: str) -> None:
        """Forget an object the probe removed itself. Called by the removal request, not by hand."""
        self._owned = [
            item for item in self._owned if not (item.server is server and item.removal == removal)
        ]

    def note(self, server: Any, method: str, path: str, payload: Any) -> None:
        """Record what a request just created, or forget what it just removed.

        `payload` is whatever the server answered, parsed where it could be. A creation is only
        recorded here when the server actually returned an identifier: registering an object off
        a refusal would guess at one that may not exist, and make the teardown report a leak on
        every probe that measures a refusal. **A refused `POST /Playlists` can still have created
        a playlist** (measured 2026-09-01), and that one is found by `Server._request`, which can
        ask the server what carries the name - this cannot.

        A successful deletion of a playlist also stops its settle clock, and hands its folder to
        `leftover_folders` to look for.
        """
        if method == "DELETE":
            self.disown(server, path)
            parts = path.split("/")
            if len(parts) == 3 and parts[1] == "Items":
                key = _playlist_key(parts[2])
                self._written.pop(key, None)
                if key in self._paths:
                    self._deleted.append(self._paths.pop(key))
                    self._last_deletion = self.clock()
            return
        if method != "POST":
            return
        for creation in CREATES:
            if path != creation.post:
                continue
            identifier = _identifier_in(payload)
            if identifier:
                self.own(server, creation.removal.format(id=identifier), creation.what)
                if creation.what == "playlist":
                    self.stamp(identifier)
            return

    def teardown(self) -> List[Outstanding]:
        """Remove everything still owned, newest first, and say what could not be removed.

        Newest first because a run creates a seat and then a playlist inside it, and removing the
        account first would take the token the playlist has to be removed with.

        Every removal is attempted even when an earlier one failed: one dead object must not take
        the rest of the cleanup with it, which is the failure mode the `finally` in each of the
        probes could not cover either.

        Each removal goes through the connection's own `DELETE`, so a playlist written to moments
        ago waits out `PLAYLIST_SETTLE` here exactly as it would in a probe's own teardown.
        """
        outstanding: List[Outstanding] = []
        for item in reversed(self._owned):
            try:
                item.server.delete(item.removal)
                self.removed += 1
                self.strays_removed += 1 if item.stray else 0
            except ProbeError as failure:
                outstanding.append(Outstanding(item, _why(failure), str(failure)))
            except Exception as failure:  # a teardown reports, it never raises
                outstanding.append(Outstanding(item, LEAKED, repr(failure)))
        self._owned = []
        return outstanding


def _directory(reader: Any, folder: str) -> Optional[List[Any]]:
    """What `/Environment/DirectoryContents` lists in a folder, or None when it may not be asked.

    None rather than an exception for **any** failure: the look is best effort, and a caller who
    is not an administrator - or a server that stopped answering - has found nothing.
    """
    try:
        rows = reader.get_where(
            "/Environment/DirectoryContents", {"path": folder, "includeDirectories": "true"}
        )
    except Exception:
        return None
    return rows if isinstance(rows, list) else None


def _playlist_key(playlist_id: Any) -> str:
    """One spelling for an identifier the reference accepts two ways: with dashes, and without."""
    return str(playlist_id).replace("-", "").lower()


def _field(mapping: Any, name: str) -> Any:
    """A property of a request body or query, read the way the reference binds it: ignoring case."""
    if not isinstance(mapping, dict):
        return None
    for key, value in mapping.items():
        if isinstance(key, str) and key.lower() == name.lower() and value not in (None, ""):
            return value
    return None


class Snapshot:
    """The playlists that already carried a name, taken just before a `POST /Playlists` asks for it.

    `before` is None when the look failed, and then nothing is looked for afterwards either: a
    playlist that was merely *not seen* before is not one the request created, and the sweep that
    follows a refusal deletes what it finds.
    """

    def __init__(self, names: Set[str], viewer: Any, before: Optional[Dict[str, str]]) -> None:
        self.names = names
        self.viewer = viewer
        self.before = before


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

    # -- credentials -------------------------------------------------------------------------

    def authorization(self, token: str | None = None) -> str:
        """The `Authorization` header value this probe sends, with `Token=` when it holds one.

        **One header carries the whole credential**, which is the reference's own canonical
        mechanism rather than a convenience: `AuthorizationContext` reads `Token` out of the
        parsed `Authorization` header first, and only falls back to the `X-Emby-Token` and
        `X-MediaBrowser-Token` headers when the server has `EnableLegacyAuthorization` switched
        on `[source: Jellyfin.Server.Implementations/Security/AuthorizationContext.cs:80-101,
        229-237 @ v10.11.11]`. The same flag gates `X-Emby-Authorization`, which is why the pair
        this client used to send was never the mechanism - it was the fallback, and it worked
        only because the servers it was pointed at had the flag on.

        **The third client to make this move, and the one that reaches the live server.**
        `tools/_reference.py` and `tools/differential.py` made it on 2026-09-11, because a
        12.0.0 instance could not be stood up at all without it. This file is what all 70
        `probe_*.py` scripts speak, so until now step 3 of
        [conformance.md's bump procedure](../docs/compatibility/conformance.md) - *re-run every
        probe script under `tools/`* - had no working client for a 12.0.0 server, and neither
        did any probe pointed at an operator's server that had been upgraded underneath it.

        Measured against one that had: `X-Emby-Authorization` answers `400` on
        `/Users/AuthenticateByName` and `X-Emby-Token` answers `401` on `/Users/Me`, where one
        `Authorization` header carrying the same components answers `200` to both
        `[probe: manual requests via tools/_probe.py, Jellyfin 12.0.0, 2026-09-12]`. It is not a
        12-only spelling and not a fork: 10.11.11 answers `200` to either, so one header serves
        both versions.

        **A probe that sends no token still sends no header**, which is unchanged and load-bearing:
        `send_token=False` is how a probe asks whether a route requires a credential at all, and
        002's answer is not the obvious one.
        """
        parts = [
            f'Client="{CLIENT}"',
            f'Device="{CLIENT}"',
            f'DeviceId="{self.device_id}"',
            f'Version="{VERSION}"',
        ]
        if token:
            parts.append(f'Token="{token}"')
        return "MediaBrowser " + ", ".join(parts)

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
            headers["Authorization"] = self.authorization(self.token)
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

        # The register's two pre-request duties (see `Register`): list what already carries the
        # name a creation asks for, and let a playlist written to moments ago settle before it
        # is deleted.
        snapshot = None
        if method == "POST" and path == "/Playlists" and self.token and send_token:
            snapshot = self._snapshot(params, body, raw_body)
        OWNED.settle(method, path)

        # S310: the URL is supplied by the operator running the probe against their own server.
        # Restricting the scheme here would stop a probe reaching a server on a custom port or
        # behind a proxy, which is the normal case rather than the exotic one.
        request = urllib.request.Request(url, data=data, headers=headers, method=method)  # noqa: S310
        refused: Optional[urllib.error.HTTPError] = None
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310
                status, answered, payload = response.status, dict(response.headers), response.read()
        except urllib.error.HTTPError as exc:
            refused = exc
            status, answered, payload = exc.code, dict(exc.headers or {}), exc.read()
            exc.close()
        except urllib.error.URLError as exc:
            OWNED.written(method, path)
            raise ProbeError(f"{method} {path} -> {exc.reason}", transport=True) from exc

        OWNED.written(method, path)
        if refused is None:
            OWNED.note(self, method, path, payload)
        if snapshot is not None:
            self._after_creation(snapshot, b"" if refused is not None else payload)

        if refused is not None and not raw:
            raise ProbeError(
                f"{method} {path} -> HTTP {status}: {payload[:200]!r}", status=status
            ) from refused
        if raw:
            return status, answered, payload
        if not payload:
            return None
        return json.loads(payload)

    # -- what a creation made, and what a refused one made anyway ------------------------------

    def _snapshot(self, params: Any, body: Any, raw_body: bytes | None) -> Snapshot | None:
        """The playlists already carrying the name a `POST /Playlists` is about to ask for.

        **A refusal on that route does not mean nothing was created.** `CreatePlaylist` creates
        the folder and the row and only then resolves the item ids, which it does inside
        `AddToPlaylistInternal`; an id that resolves to nothing throws from there
        [source: Emby.Server.Implementations/Playlists/PlaylistManager.cs:80-160 @ v10.11.11].
        Measured against 10.11.11 on 2026-09-01: `{"Ids": [<a track>, <32 zeros>]}` answers
        `400 Error processing request.` and leaves a playlist behind whose id the caller is never
        told - which is the other of the two ways the 28 leaked playlists were left.

        So the names are read off the request - the body's and the query's, since a probe sends
        both on purpose - and the playlists already carrying one are listed as the owner the body
        names, falling back to this connection's own account when it may not list as the owner.
        """
        if raw_body is not None:
            try:
                body = json.loads(raw_body)
            except (ValueError, TypeError):
                body = None
        names = {str(name) for name in (_field(body, "Name"), _field(params, "name")) if name}
        if not names:
            return None
        owner = _field(body, "UserId") or _field(params, "userId") or self.user_id
        for viewer in dict.fromkeys([str(owner) if owner else None, self.user_id]):
            if viewer is None:
                continue
            before = self._playlists_named(names, viewer)
            if before is not None:
                return Snapshot(names, viewer, before)
        return Snapshot(names, None, None)

    def _playlists_named(self, names: Set[str], viewer: Any) -> Dict[str, str] | None:
        """Id -> folder of every playlist `viewer` can see under one of these names, or None."""
        try:
            found = self._request(
                "GET",
                "/Items",
                params={
                    "Recursive": "true",
                    "IncludeItemTypes": "Playlist",
                    "UserId": viewer,
                    "Fields": "Path",
                },
            )
        except (ProbeError, ValueError):
            return None
        if not isinstance(found, dict):
            return None
        return {
            str(row["Id"]): str(row.get("Path") or "")
            for row in found.get("Items") or []
            if isinstance(row, dict) and row.get("Id") and row.get("Name") in names
        }

    def _after_creation(self, snapshot: Snapshot, payload: bytes) -> None:
        """Remember where a created playlist lives, or find what a refused creation made anyway.

        What the look finds is **owned as a stray and not returned**: it is residue to be removed,
        not a measurement, and a probe that reads a refusal as "nothing was created" still reads
        the answer it was given correctly. It is only ever a playlist that carries the requested
        name and was not there a moment before, so nothing the operator owns can be swept.
        """
        identifier = _identifier_in(payload)
        if identifier:
            if snapshot.viewer is not None:
                OWNED.remember(self, identifier, self._folder_of(identifier, snapshot.viewer))
            return
        if snapshot.before is None:
            return
        after = self._playlists_named(snapshot.names, snapshot.viewer)
        for found, folder in sorted((after or {}).items()):
            if found in snapshot.before:
                continue
            OWNED.own(self, f"/Items/{found}", STRAY, stray=True)
            OWNED.stamp(found)
            OWNED.remember(self, found, folder)

    def _folder_of(self, identifier: str, viewer: Any) -> str:
        """Where on the server's disk a playlist lives, when this connection may be told. Or ''."""
        try:
            status, _, payload = self._request(
                "GET",
                f"/Items/{identifier}",
                params={"userId": viewer, "fields": "Path"},
                raw=True,
            )
            found = json.loads(payload) if status == 200 and payload else {}
        except (ProbeError, ValueError):
            return ""
        return str(found.get("Path") or "") if isinstance(found, dict) else ""

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
            headers["Authorization"] = self.authorization(self.token)
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
            extra_headers={"Authorization": self.authorization()},
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


def report_cleanup(
    outstanding: List[Outstanding],
    removed: int,
    strays: int = 0,
    settled: float = 0.0,
    settles: int = 0,
    folders: Sequence[str] = (),
) -> bool:
    """Say what the register removed and what it could not, and answer whether that is a leak.

    **Only `LEAKED` is a leak.** A `401` means the token was revoked out from under the run and a
    connection refused means the server is not there any more; both were measured on 2026-09-02
    (010 T12) and neither is the probe forgetting to clean up. Reporting them as leaks is how an
    enforcement gets ignored, and an ignored enforcement is worse than none - which is spec
    section 6's *"does not cry wolf"* applied to the teardown rather than to the comparison.

    An object the register removed is **reported and not failed**: the contract is about what is
    left on the server, and the server is clean either way. The line exists so that a probe
    relying on the shared teardown is visible rather than silent. A **stray** - a playlist a
    refused creation made anyway - is counted apart, because no probe was told its id and no
    probe's own teardown could have removed it.

    The three playlist lines are reports and never a failure. `settled` is how long deletions
    waited for a playlist to settle (`PLAYLIST_SETTLE`), said so that a measured deletion is not
    delayed in silence; `folders` are the ones `Register.leftover_folders` found still on the
    server's disk, which only an administrator can look for.
    """
    if removed - strays:
        print(
            f"cleanup: the shared register removed {removed - strays} object(s) the probe had not "
            f"removed itself. That is the contract holding, not a failure - but a probe that "
            f"leaves its own creations to the register is one whose own teardown is worth a look.",
            file=sys.stderr,
        )
    if strays:
        print(
            f"cleanup: the shared register removed {strays} playlist(s) a refused POST /Playlists "
            f"had created anyway. The reference creates the playlist before it resolves the ids "
            f"that make it refuse, and never answers the id - so no probe could have removed "
            f"these.",
            file=sys.stderr,
        )
    if settles:
        print(
            f"cleanup: {settles} playlist deletion(s) waited {settled:.1f}s in total for the "
            f"refresh the reference queues after a write (_probe.PLAYLIST_SETTLE), because a "
            f"deletion inside that window leaves the folder on the server's disk.",
            file=sys.stderr,
        )
    if folders:
        print(
            "cleanup: LEAKED folders - deleted, but these are still on the server's disk and the "
            "next library scan will turn them back into playlists: "
            + ", ".join(folders)
            + ". Remove them from the server's filesystem, and treat _probe.PLAYLIST_SETTLE as too "
            "short for this server.",
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
                outstanding = OWNED.teardown()
                leaked = report_cleanup(
                    outstanding,
                    OWNED.removed,
                    strays=OWNED.strays_removed,
                    settled=OWNED.settled,
                    settles=OWNED.settles,
                    folders=OWNED.leftover_folders(),
                )
            return CLEANUP_FAILED if leaked else code
    except ProbeError as exc:
        print(f"cannot answer the question: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130
