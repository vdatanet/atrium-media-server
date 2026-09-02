#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""A Jellyfin this project owns, uses once, and destroys - 010 plan section 6.5, ADR-0007.

**The destruction is the invariant, so the thing is a context manager and nothing else.** Every
resource a run creates carries one label, `__exit__` removes them on the success path and on the
exception path alike, and `__enter__` sweeps whatever a killed run left before it starts anything
of its own - because the only cleanup that survives a kill is the one the *next* run performs
(008 section 6.7 makes the same argument for the transcode scratch root). The reason this is
enforced rather than promised is on an operator's server: on 2026-09-01 it still held **28
playlists** left behind by 009's probe runs, each under the name those probes create them with,
every one of which had a cleanup written in its own docstring.

**Nothing here is written to a server somebody owns.** That is the whole point of the instance:
the fixture comparison needs a library on the *other* side, adding a library is a write, and the
only reachable Jellyfin was somebody's production server
([ADR-0007](../docs/decisions/0007-a-container-runtime-for-the-reference-instance.md)).

The runtime is invoked as a **subprocess through its command line** and never as a library, so
`tools/` keeps its standard-library-only rule on the Python 3.9 floor (D-2). Docker and Podman
take the same arguments for everything used here.

**The image is pinned by digest and never by tag** (ADR-0007). A tag moves; a digest is the
version this project measured, and it is what the report prints beside the Atrium sha so that a
difference reproducing on one machine only can be told from a difference that is real.
`docs/compatibility/reference-target.md` section 1 carries the same digest, and
`tests/conformance/test_differential.py` fails when the two drift apart.

**When it cannot start, the run neither fails nor passes.** Every case and named row that declared
`needs: fixture` is reported outstanding with the reason, and `is_clean()` is false - which is
ADR-0007's *"the dependency buys coverage; its absence costs coverage and says so"*. This module
therefore raises a typed error naming what was missing rather than dying, and
`tools/differential.py` turns that sentence into the reason it prints.

Usage:
    from _reference import InstanceSpec, ReferenceInstance
    with ReferenceInstance(InstanceSpec(fixture_root=tree)) as instance:
        ...                                    # instance.url, instance.administrator
    # the container, its volumes and everything written inside them are gone here
"""

from __future__ import annotations

import http.client
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import time
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import TracebackType
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

# --------------------------------------------------------------------------------------------
# What is pinned
# --------------------------------------------------------------------------------------------

#: The published Jellyfin image, and the **multi-architecture index** digest rather than one
#: platform's. A contributor on arm64 and a maintainer on amd64 pin the same line this way, which
#: is the difference a per-platform digest would silently introduce between two machines that
#: believe they measured the same reference.
IMAGE_REPOSITORY = "jellyfin/jellyfin"
IMAGE_DIGEST = "sha256:aefb67e6a7ff1debdd154a78a7bbb780fd0c873d8639210a7f6a2016ad2b35db"
IMAGE = IMAGE_REPOSITORY + "@" + IMAGE_DIGEST

#: The version that digest is the image of, kept beside it so the two cannot drift silently.
IMAGE_VERSION = "10.11.11"

#: **One label on every resource a run creates, fixed across runs.** Fixed is the property, not a
#: convenience: a random one would leave the next run unable to recognise what a killed one left,
#: which is the same argument `tools/differential.py` makes for its fixed seat names.
LABEL = "net.atrium.reference"
LABEL_VALUE = "single-use"
LABEL_FILTER = LABEL + "=" + LABEL_VALUE

#: Names are prefixed so a human reading `docker ps` can see whose they are; the sweep matches on
#: the label and never on the name, because a name is a convenience and a label is a contract.
NAME_PREFIX = "atrium-reference-"

#: The port inside the container, and the address the published one is bound to. Loopback only:
#: this instance holds a fixture and no secrets, and it still has no business being reachable
#: from another machine.
CONTAINER_PORT = 8096
LOOPBACK = "127.0.0.1"

#: Where the fixture tree is mounted, **read-only**. Deliberately not under `/media`: the image
#: declares `/config` and `/cache` as volumes and nothing else, so a mount anywhere else is a
#: plain bind and cannot pick up an anonymous volume that the sweep would then not know about
#: `[probe: docker image inspect jellyfin/jellyfin@sha256:aefb67e6…, 2026-09-02]`.
FIXTURE_MOUNT = "/fixture"

#: The runtimes ADR-0007 names, in the order they are looked for, and the variable that overrides
#: the choice on a machine that has both.
RUNTIMES: Tuple[str, ...] = ("docker", "podman")
ENV_RUNTIME = "ATRIUM_CONTAINER_RUNTIME"

#: The scheduled task the reference runs a library scan as `[spec: GetTasks, TaskInfo.Key]`.
SCAN_TASK_KEY = "RefreshLibrary"

#: The item types a library of this fixture produces, spelled as the reference spells them when it
#: looks a type's options up - `item.GetType().Name`
#: `[source: MediaBrowser.Providers/Manager/ProviderManager.cs:384 @ v10.11.11]`. A type named here
#: with an **empty** fetcher list has every remote provider disabled for it, because the library's
#: own type options are an allowlist and not a deny list: *"return libraryTypeOptions.
#: MetadataFetchers.Contains(name)"*
#: `[source: MediaBrowser.Controller/BaseItemManager/BaseItemManager.cs:42 @ v10.11.11]`. A type
#: absent from the list falls through to the server's defaults, which is why the list is spelled
#: out rather than inferred from what a scan happens to produce.
FETCHED_TYPES: Tuple[str, ...] = (
    "Movie",
    "Series",
    "Season",
    "Episode",
    "MusicArtist",
    "MusicAlbum",
    "Audio",
    "MusicVideo",
    "Video",
    "Folder",
    "BoxSet",
    "Trailer",
)


# --------------------------------------------------------------------------------------------
# Failures, typed so that a caller can degrade rather than die
# --------------------------------------------------------------------------------------------


class InstanceError(RuntimeError):
    """The instance could not be stood up, or could not be destroyed.

    Every message names what was missing, because it is printed as the reason a `needs: fixture`
    row is outstanding and *"outstanding"* with no reason is a skip wearing a longer word.
    """


class RuntimeAbsentError(InstanceError):
    """No container runtime on this machine. The commonest reason, and never an error at all.

    A machine without one still runs the sweep against a reachable server and everything in the
    default CI job; what it loses is the fixture half, and the run says so (ADR-0007).
    """


class WizardRefusedError(InstanceError):
    """A first-time-setup operation answered a non-2xx. The body is the finding.

    Plan section 6.5 step 4 reads the authorization policy of those operations **from a document**
    and says so: *"it is named here so that it is checked rather than discovered"*. A wizard that
    refuses is a version difference, and the status and body are what say which.
    """


class ScanTimeoutError(InstanceError):
    """The library scan did not finish inside the deadline; the elapsed time is in the message."""


# --------------------------------------------------------------------------------------------
# The runtime, as a command line
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Completed:
    """One invocation of the runtime. Kept whole so a failure can print what it actually ran."""

    args: Tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    @property
    def out(self) -> str:
        return self.stdout.strip()

    def failure(self, doing: str) -> str:
        detail = self.stderr.strip() or self.stdout.strip() or "no output"
        return f"{doing}: `{' '.join(self.args)}` exited {self.returncode}: {detail}"


class Runtime:
    """The container runtime, invoked as a subprocess. Injectable, so the suite drives a stub.

    ADR-0007 rejected an SDK for two reasons and both are load-bearing here: `tools/` is standard
    library only on a 3.9 floor, and the subprocess boundary is the one that survives a change of
    runtime - Docker and Podman accept the same arguments for one container with three mounts and
    one published port.
    """

    def __init__(self, binary: str) -> None:
        self.binary = binary

    @property
    def name(self) -> str:
        return Path(self.binary).name

    @staticmethod
    def discover(preferred: str = "") -> Runtime:
        """The runtime on this machine, by absolute path, or `RuntimeAbsent` naming the candidates.

        Resolved with `shutil.which` rather than spelled as a bare name, so the subprocess never
        depends on how `PATH` is searched at call time.
        """
        wanted = preferred or os.environ.get(ENV_RUNTIME, "")
        candidates = (wanted,) if wanted else RUNTIMES
        for candidate in candidates:
            found = shutil.which(candidate)
            if found:
                return Runtime(found)
        looked = ", ".join(candidates)
        raise RuntimeAbsentError(
            f"no container runtime on this machine (looked for {looked}). The fixture half of a "
            "run needs one, because the comparison needs a library on the other server and "
            "adding a library is a write - see ADR-0007. Install one, or pass --reference-url "
            "naming an instance somebody else stood up"
        )

    def __call__(self, *args: str, timeout: float = 300.0) -> Completed:
        """Run the runtime once. A non-zero exit is returned, never raised: what it means is
        the caller's to decide, and several callers treat one as an ordinary answer."""
        command = (self.binary, *args)
        try:
            finished = subprocess.run(  # noqa: S603 - the arguments are this module's own
                list(command),
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except OSError as failure:
            raise InstanceError(f"could not run `{' '.join(command)}`: {failure}") from failure
        except subprocess.TimeoutExpired as failure:
            raise InstanceError(
                f"`{' '.join(command)}` did not finish within {timeout:g}s"
            ) from failure
        return Completed(
            args=command,
            returncode=finished.returncode,
            stdout=finished.stdout.decode("utf-8", "replace"),
            stderr=finished.stderr.decode("utf-8", "replace"),
        )


# --------------------------------------------------------------------------------------------
# The instance's own client
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Answer:
    status: int
    headers: Mapping[str, str]
    raw: bytes

    @property
    def body(self) -> Any:
        if not self.raw:
            return None
        try:
            return json.loads(self.raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return None

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


class Api:
    """The smallest client that can drive a setup wizard, on `http.client`.

    Deliberately not `tools/differential.py`'s `Wire`: that module imports **this** one, and a
    module that has to exist before any seat does cannot depend on the module whose seats it
    hands back. Deliberately not `tools/_probe.py`'s `Server` either - its `connect` refuses a
    server whose wizard has not run, which is every server this class talks to for its first four
    requests.
    """

    def __init__(self, url: str, timeout: float = 30.0) -> None:
        parsed = urllib.parse.urlsplit(url if "://" in url else "http://" + url)
        self.url = url.rstrip("/")
        self.scheme = parsed.scheme or "http"
        self.host = parsed.hostname or LOOPBACK
        self.port = parsed.port
        self.prefix = parsed.path.rstrip("/")
        self.timeout = timeout
        self.token = ""

    def request(
        self,
        method: str,
        path: str,
        body: Any = None,
        query: Optional[Mapping[str, Any]] = None,
    ) -> Answer:
        clean = {key: value for key, value in (query or {}).items() if value is not None}
        target = (
            self.prefix
            + path
            + (("?" + urllib.parse.urlencode(clean, doseq=True)) if clean else "")
        )
        headers = {
            "Accept": "application/json",
            "X-Emby-Authorization": (
                'MediaBrowser Client="atrium-reference", Device="atrium-reference", '
                'DeviceId="atrium-reference-0000", Version="0.1"'
            ),
        }
        payload: Optional[bytes] = None
        if body is not None:
            payload = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if self.token:
            headers["X-Emby-Token"] = self.token
        connection: Any
        if self.scheme == "https":
            connection = http.client.HTTPSConnection(self.host, self.port, timeout=self.timeout)
        else:
            connection = http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)
        try:
            connection.request(method, target, body=payload, headers=headers)
            answer = connection.getresponse()
            return Answer(
                status=answer.status, headers=dict(answer.getheaders()), raw=answer.read()
            )
        finally:
            connection.close()


#: How an instance obtains its client. Injected so the suite can drive the whole lifecycle with a
#: stub, which is what keeps these tests inside a suite that fails any test opening a socket.
ApiFactory = Callable[[str], Api]


# --------------------------------------------------------------------------------------------
# What a run asks for
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Library:
    """One library the instance is given over the mounted fixture tree.

    `collection_type` empty means a mixed-content library, which is what the reference makes when
    `AddVirtualFolder` is called without one `[spec: AddVirtualFolder]`. Which world an instance
    is given, and in how many libraries, is **D-4** and is measured by `probe_reference_scan.py`
    (010 T10); this class is what lets that measurement ask either shape without changing this
    module.

    **`internet_providers` defaults to off, and that default is a measurement rather than a
    preference.** With it on - which is what a `LibraryOptions` body naming only `PathInfos`
    binds to - the reference's reading of the fixture is not a reading of the fixture: over the
    003 tree it named a film `WALL-E's Treasures & Trinkets`, an episode `Highlander: Reunion`
    and another `12:00 A.M.-1:00 A.M.`, none of which is in the tree or derivable from it. A
    remote provider answered, so the comparison AC-2 asks for would have compared this project's
    scanner against a third party's database, on values that change without either server
    changing `[probe: tools/probe_reference_scan.py, Jellyfin 10.11.11, 2026-09-02]`. The field
    exists rather than the default being hard-coded because the difference between the two
    readings is the measurement, and a probe has to be able to take both.
    """

    name: str
    collection_type: str = ""
    subpath: str = ""
    internet_providers: bool = False

    def path_in(self, mount: str) -> str:
        return mount + "/" + self.subpath.strip("/") if self.subpath.strip("/") else mount


#: The default when a caller names none: one mixed library over the whole tree. Mixed rather than
#: `movies`, because naming a collection type is an assertion about what the tree holds and this
#: module does not know.
DEFAULT_LIBRARIES: Tuple[Library, ...] = (Library(name="Fixture"),)


def library_options(library: Library, path: str) -> Dict[str, Any]:
    """The `LibraryOptions` body one library is added with `[spec: AddVirtualFolder]`.

    Everything not named here is left to whatever an absent value binds to, deliberately: a
    freshly created library has no policy anybody set, and what this instance exists to measure
    is the reference's own defaults. **Remote metadata is the one exception**, and the shape of
    the exception is a finding rather than a choice.

    `LibraryOptions.EnableInternetProviders` is the property that reads like the switch and is
    not one: it is declared `[spec: LibraryOptions]`, it is stored, it reads back `false` - and
    **nothing in the reference consults it**, the declaration on
    `MediaBrowser.Model/Configuration/LibraryOptions.cs:64 @ v10.11.11` being its only occurrence
    in the source. Set alone it changed **nothing**: the reading over the 003 tree was identical
    to the one taken with it unset, remote titles and all
    `[probe: tools/probe_reference_scan.py, Jellyfin 10.11.11, 2026-09-02]`. It is still sent,
    because it is what the document declares and a later version may honour it, but it is not
    what does the work.

    What does the work is the library's own **type options**, which are an allowlist: a type that
    has them enables exactly the fetchers they name
    `[source: MediaBrowser.Controller/BaseItemManager/BaseItemManager.cs:42 @ v10.11.11]`. Empty
    lists for every type the fixture produces therefore leave the local readers - the `.nfo`
    sidecars, the embedded tags - and take the network out of the reading.
    """
    options: Dict[str, Any] = {
        "PathInfos": [{"Path": path}],
        "EnableInternetProviders": library.internet_providers,
    }
    if not library.internet_providers:
        options["TypeOptions"] = [
            {"Type": name, "MetadataFetchers": [], "ImageFetchers": [], "ImageOptions": []}
            for name in FETCHED_TYPES
        ]
    return options


@dataclass(frozen=True)
class InstanceSpec:
    """What to stand up (plan section 5).

    The deadlines are fields rather than constants because a fixture that cannot be scanned in
    minutes is a fixture problem and the person holding it is the one who knows (plan section 7).
    """

    fixture_root: Path
    image: str = IMAGE
    label: str = LABEL
    libraries: Tuple[Library, ...] = DEFAULT_LIBRARIES
    server_name: str = "atrium-reference"
    ready_timeout: float = 180.0
    scan_timeout: float = 900.0
    poll: float = 1.0

    @property
    def digest(self) -> str:
        """The digest this spec pins, or `""` for an image named some other way."""
        _, _, digest = self.image.partition("@")
        return digest


@dataclass(frozen=True)
class Credentials:
    """The administrator the wizard creates. The only account this module makes."""

    username: str
    password: str = field(repr=False)


# --------------------------------------------------------------------------------------------
# The instance
# --------------------------------------------------------------------------------------------


def free_port() -> int:
    """A loopback port nothing is listening on, asked of the kernel rather than guessed."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((LOOPBACK, 0))
        return int(probe.getsockname()[1])


def _announce(message: str) -> None:
    print("reference: " + message, file=sys.stderr)


class ReferenceInstance:
    """A Jellyfin this project owns, uses once, and destroys (plan section 5, section 6.5).

    A context manager, because the destruction is the invariant. `__enter__` performs plan
    section 6.5 in order - sweep, start, wait for the API, configure with no human, wait for the
    scan on the server's own answer - and `__exit__` destroys the container and its volumes on
    both paths, deleting **nothing** inside the instance first: the accounts, playlists and
    libraries die with it, which is spec section 3.1's *"the difference between a cleanup that
    must be perfect and one that only has to be tidy"*.
    """

    def __init__(
        self,
        spec: InstanceSpec,
        runtime: Optional[Runtime] = None,
        api_factory: Optional[ApiFactory] = None,
        port: Optional[int] = None,
        announce: Callable[[str], None] = _announce,
        make_password: Optional[Callable[[], str]] = None,
        now: Callable[[], float] = time.monotonic,
        pause: Callable[[float], None] = time.sleep,
    ) -> None:
        self.spec = spec
        self._runtime = runtime
        self._api_factory = api_factory or (lambda url: Api(url))
        self._port = port
        self._announce = announce
        self._make_password = make_password or (lambda: secrets.token_hex(16))
        self._now = now
        self._pause = pause

        stamp = secrets.token_hex(4)
        self.container = NAME_PREFIX + stamp
        self.volumes: Tuple[str, ...] = (
            NAME_PREFIX + stamp + "-config",
            NAME_PREFIX + stamp + "-cache",
        )
        self.url = ""
        self.api: Optional[Api] = None
        self.administrator: Optional[Credentials] = None
        self.administrator_id = ""
        self.swept = 0
        self._started = False

    # -- what a report prints ------------------------------------------------------------------

    @property
    def image(self) -> str:
        return self.spec.image

    @property
    def digest(self) -> str:
        return self.spec.digest

    def runtime(self) -> Runtime:
        """The runtime, discovered once. Never at construction: `--help` must start nothing."""
        if self._runtime is None:
            self._runtime = Runtime.discover()
        return self._runtime

    # -- lifecycle -----------------------------------------------------------------------------

    def __enter__(self) -> ReferenceInstance:
        runtime = self.runtime()
        self.swept = sweep(runtime, announce=self._announce)
        try:
            self._start(runtime)
            self._wait_for_api()
            self._configure()
            self._wait_for_scan()
        except BaseException:
            # A half-started instance is not a smaller instance. Whatever exists is destroyed
            # here, so the reason that reaches the caller does not also leave a container running
            # for the next run's sweep to find.
            self._destroy(failed=True)
            raise
        return self

    def __exit__(
        self,
        exc_type: Optional[type],
        exc: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> None:
        self._destroy(failed=exc_type is not None)

    # -- step 2: start -------------------------------------------------------------------------

    def _start(self, runtime: Runtime) -> None:
        root = self.spec.fixture_root
        if not root.is_dir():
            raise InstanceError(
                f"the fixture tree {root} is not a directory, and an instance with nothing "
                "mounted would scan an empty library and compare two of them"
            )
        self._ensure_image(runtime)

        for volume in self.volumes:
            created = runtime("volume", "create", "--label", LABEL_FILTER, volume)
            if not created.ok:
                raise InstanceError(created.failure("creating the instance's data volume"))

        port = self._port or free_port()
        self.url = f"http://{LOOPBACK}:{port}"
        arguments = [
            "run",
            "--detach",
            # Even a lost `finally` then leaves nothing but the volumes, which the sweep takes.
            "--rm",
            "--name",
            self.container,
            "--label",
            LABEL_FILTER,
            "--label",
            LABEL + ".created=" + datetime.now(timezone.utc).isoformat(),
            "--publish",
            f"{LOOPBACK}:{port}:{CONTAINER_PORT}",
            "--volume",
            f"{self.volumes[0]}:/config",
            "--volume",
            f"{self.volumes[1]}:/cache",
            # **Read-only, and a bind rather than a copy.** Read-only so neither server can change
            # the thing both are measured against; a bind because
            # `tests/fixtures/library/generate.py` stamps every file with one fixed modification
            # time, and a copy that did not preserve it would put a difference into `DateCreated`
            # on every item - a field the allowlist excuses, which is worse than a visible
            # failure because the noise would be invisible (ADR-0007).
            "--volume",
            f"{root.resolve()}:{FIXTURE_MOUNT}:ro",
            self.spec.image,
        ]
        started = runtime(*arguments)
        if not started.ok:
            self._started = True  # a failed `run` can still have left a container to remove
            raise InstanceError(started.failure("starting the reference instance"))
        self._started = True
        self._announce(f"started {self.container} on {self.url} from {self.spec.image}")

    def _ensure_image(self, runtime: Runtime) -> None:
        """Pull the pinned image if it is not already here, and say which of the two happened."""
        if runtime("image", "inspect", self.spec.image).ok:
            return
        self._announce(f"pulling {self.spec.image}")
        pulled = runtime("pull", self.spec.image, timeout=1800.0)
        if not pulled.ok:
            raise InstanceError(
                pulled.failure(f"pulling the pinned reference image {self.spec.image}")
            )

    # -- step 3: wait for the API, not the process ---------------------------------------------

    def _wait_for_api(self) -> None:
        """`GET /System/Info/Public` answering a `ProductName` naming Jellyfin.

        Not a port probe and not the container's own state: **a listening socket is not a
        configured server**, and this is the same check `tools/_probe.py`'s `connect` makes for
        its own reason.
        """
        api = self._api_factory(self.url)
        self.api = api
        deadline = self._now() + self.spec.ready_timeout
        last = "nothing answered"
        while self._now() < deadline:
            try:
                answer = api.request("GET", "/System/Info/Public")
            except OSError as failure:
                last = str(failure)
            else:
                body = answer.body
                if answer.ok and isinstance(body, dict):
                    product = str(body.get("ProductName", ""))
                    if "jellyfin" in product.lower():
                        self._announce(
                            f"ready: {product} {body.get('Version', 'unknown')} on {self.url}"
                        )
                        return
                    last = f"ProductName was {product!r}"
                else:
                    last = f"GET /System/Info/Public answered {answer.status}"
            self._pause(self.spec.poll)
        raise InstanceError(
            f"the reference instance did not answer within {self.spec.ready_timeout:g}s "
            f"({last}). {self._logs()}"
        )

    def _logs(self, lines: int = 40) -> str:
        """The container's own last words, because a start that failed says why in them."""
        if self._runtime is None or not self._started:
            return "no container to read logs from"
        got = self._runtime("logs", "--tail", str(lines), self.container)
        text = (got.stdout + got.stderr).strip()
        return f"last {lines} lines of {self.container}:\n{text}" if text else "the log was empty"

    # -- step 4: configure, with no human ------------------------------------------------------

    def _configure(self) -> None:
        """The four first-time-setup operations, then the library, with nobody at a keyboard.

        `[spec: UpdateInitialConfiguration, UpdateStartupUser, CompleteWizard, AddVirtualFolder]`.
        All four declare the **first-time-setup** policy where `POST /Users/New` declares
        elevation `[spec: the security requirement declared on those operations]`, which is what
        makes an unattended sequence possible at all - and plan section 6.5 read that from the
        document rather than measuring it, so this is where it is checked.
        """
        api = self.api
        if api is None:  # pragma: no cover - _wait_for_api sets it before this runs
            raise InstanceError("the instance has no client")
        password = self._make_password()
        administrator = Credentials(username="atrium-reference-admin", password=password)

        self._wizard(
            api,
            "POST",
            "/Startup/Configuration",
            {
                "ServerName": self.spec.server_name,
                "UICulture": "en-US",
                "MetadataCountryCode": "US",
                "PreferredMetadataLanguage": "en",
            },
        )
        # **The step plan section 6.5 predicted it might need, and it is a read.** `POST
        # /Startup/User` answers `404` while no user exists - it fetches the first user and
        # returns `NotFound()` when there is none
        # `[source: Jellyfin.Api/Controllers/StartupController.cs:130-137 @ v10.11.11]` - and the
        # thing that makes one is the **GET** beside it, which calls the user manager's own
        # initialisation before reading
        # `[source: Jellyfin.Api/Controllers/StartupController.cs:107-114 @ v10.11.11]`. So the
        # wizard's user operation is a **rename of an account the read created**, not a creation,
        # and an unattended sequence that skips the read stops here. Measured before it was read:
        # a real instance answered exactly that `404`
        # `[probe: tools/reference_instance.py --check, Jellyfin 10.11.11, 2026-09-02]`.
        self._wizard(api, "GET", "/Startup/User", None)
        self._wizard(
            api,
            "POST",
            "/Startup/User",
            {"Name": administrator.username, "Password": administrator.password},
        )
        self._wizard(api, "POST", "/Startup/Complete", None)
        self.administrator = administrator

        signed_in = api.request(
            "POST",
            "/Users/AuthenticateByName",
            {"Username": administrator.username, "Pw": administrator.password},
        )
        body = signed_in.body
        if not signed_in.ok or not isinstance(body, dict) or "AccessToken" not in body:
            raise WizardRefusedError(
                "the administrator the wizard created could not authenticate: "
                f"POST /Users/AuthenticateByName answered {signed_in.status} "
                f"{signed_in.raw[:200]!r}"
            )
        api.token = str(body["AccessToken"])
        self.administrator_id = str(body.get("User", {}).get("Id", ""))

        for library in self.spec.libraries:
            self._add_library(api, library)

    def _wizard(self, api: Api, method: str, path: str, body: Any) -> Answer:
        answer = api.request(method, path, body=body)
        if not answer.ok:
            raise WizardRefusedError(
                f"{method} {path} answered {answer.status} {answer.raw[:400]!r}. A first-time "
                "setup operation that refuses is a version difference, and the body is the "
                "finding rather than a reason to retry"
            )
        return answer

    def _add_library(self, api: Api, library: Library) -> None:
        path = library.path_in(FIXTURE_MOUNT)
        query: Dict[str, Any] = {"name": library.name, "refreshLibrary": "true"}
        if library.collection_type:
            query["collectionType"] = library.collection_type
        answer = api.request(
            "POST",
            "/Library/VirtualFolders",
            body={"LibraryOptions": library_options(library, path)},
            query=query,
        )
        if not answer.ok:
            raise WizardRefusedError(
                f"POST /Library/VirtualFolders for {library.name!r} at {path} answered "
                f"{answer.status} {answer.raw[:400]!r}"
            )
        fetching = "internet providers on" if library.internet_providers else "no remote metadata"
        self._announce(f"library {library.name!r} added over {path} ({fetching})")

    # -- step 5: wait for the scan, on the server's own answer ---------------------------------

    def _wait_for_scan(self) -> None:
        """`GET /ScheduledTasks` until the library scan reports itself idle **having run**.

        Not a sleep, and not an item count that has stopped changing: *a count that has stopped
        changing is indistinguishable from a scan that has not started* (plan section 6.5). The
        same trap is one step nearer than the plan puts it - the scan task is `Idle` before it
        starts too - so what is waited for is a **completion that did not exist a moment ago**,
        read from the task's own `LastExecutionResult` `[spec: GetTasks, TaskResult]`.
        """
        api = self.api
        if api is None:  # pragma: no cover
            raise InstanceError("the instance has no client")
        deadline = self._now() + self.spec.scan_timeout
        started_at = self._now()
        seen_running = False
        while self._now() < deadline:
            task = self._scan_task(api)
            if task is None:
                self._pause(self.spec.poll)
                continue
            state = str(task.get("State", ""))
            if state != "Idle":
                seen_running = True
                self._pause(self.spec.poll)
                continue
            finished = task.get("LastExecutionResult") or {}
            if isinstance(finished, dict) and finished.get("EndTimeUtc"):
                elapsed = self._now() - started_at
                self._announce(
                    f"scan finished in {elapsed:.0f}s with status "
                    f"{finished.get('Status', 'unknown')!r}"
                )
                return
            if not seen_running:
                # Idle, and it has never run: the scan the library addition asked for has not
                # started. Ask for one by name rather than waiting on a state that is already
                # what it will be `[spec: StartTask]`.
                self._start_scan(api, task)
                seen_running = True
            self._pause(self.spec.poll)
        raise ScanTimeoutError(
            f"the library scan did not finish within {self.spec.scan_timeout:g}s. A fixture that "
            "cannot be scanned in minutes is a fixture problem; raise the deadline only after "
            "reading the instance's log"
        )

    def _scan_task(self, api: Api) -> Optional[Dict[str, Any]]:
        answer = api.request("GET", "/ScheduledTasks")
        body = answer.body
        if not answer.ok or not isinstance(body, list):
            return None
        for task in body:
            if isinstance(task, dict) and task.get("Key") == SCAN_TASK_KEY:
                return task
        return None

    def _start_scan(self, api: Api, task: Mapping[str, Any]) -> None:
        task_id = str(task.get("Id", ""))
        if not task_id:
            return
        started = api.request("POST", "/ScheduledTasks/Running/" + task_id)
        if not started.ok:
            raise InstanceError(
                f"the library scan could not be started: POST /ScheduledTasks/Running/{task_id} "
                f"answered {started.status}"
            )
        self._announce("the library scan was asked for by name")

    # -- teardown ------------------------------------------------------------------------------

    def destroy(self) -> Tuple[str, ...]:
        """Remove the container and the volumes. Returns what could not be removed."""
        if self._runtime is None:
            return ()
        leaked: List[str] = []
        if self._started:
            removed = self._runtime("rm", "--force", "--volumes", self.container)
            if not removed.ok and "no such container" not in removed.stderr.lower():
                leaked.append(removed.failure("removing the container"))
        for volume in self.volumes:
            gone = self._runtime("volume", "rm", "--force", volume)
            if not gone.ok and "no such volume" not in gone.stderr.lower():
                leaked.append(gone.failure(f"removing the volume {volume}"))
        self._started = False
        return tuple(leaked)

    def _destroy(self, failed: bool) -> None:
        leaked = self.destroy()
        if not leaked:
            return
        message = (
            "the run left a reference instance behind and could not remove it: "
            + "; ".join(leaked)
            + f". The next run's sweep removes anything labelled {LABEL_FILTER}, and "
            f"`{self._runtime.name if self._runtime else 'docker'} rm -f "
            f"{self.container}` removes it now."
        )
        if failed:
            # Never mask the failure already on its way out: a teardown that replaced it would
            # hide the reason the run stopped, which is `Roster._destroy`'s rule and the same one.
            self._announce(message)
            return
        raise InstanceError(message)


# --------------------------------------------------------------------------------------------
# The sweep the next run performs
# --------------------------------------------------------------------------------------------


def sweep(runtime: Optional[Runtime] = None, announce: Callable[[str], None] = _announce) -> int:
    """Destroy everything an earlier run labelled, and say how many (plan section 6.5 step 1).

    **The only cleanup that survives a killed process is the one the next run performs**, which is
    what 008 section 6.7 does to the transcode scratch root for the same reason. The count is
    returned and printed so that a leak is visible rather than silent: a run that sweeps three
    every time is a run whose teardown is not working.

    A machine with no runtime has no wreckage, so this answers `0` rather than raising - it is
    called on the degradation path too.
    """
    try:
        engine = runtime or Runtime.discover()
    except RuntimeAbsentError:
        return 0
    removed = 0
    containers = engine("ps", "--all", "--quiet", "--filter", "label=" + LABEL_FILTER)
    for container in containers.out.split():
        gone = engine("rm", "--force", "--volumes", container)
        removed += 1 if gone.ok else 0
    volumes = engine("volume", "ls", "--quiet", "--filter", "label=" + LABEL_FILTER)
    for volume in volumes.out.split():
        gone = engine("volume", "rm", "--force", volume)
        removed += 1 if gone.ok else 0
    if removed:
        announce(
            f"swept {removed} leftover(s) from an earlier run. A run that sweeps something every "
            "time has a teardown that is not working"
        )
    return removed


def stand_up(
    fixture_root: Path,
    libraries: Sequence[Library] = (),
    **overrides: Any,
) -> ReferenceInstance:
    """The instance a caller wants, unentered. `with stand_up(tree) as instance: ...`"""
    spec = InstanceSpec(
        fixture_root=Path(fixture_root),
        libraries=tuple(libraries) or DEFAULT_LIBRARIES,
        **{key: value for key, value in overrides.items() if key in _SPEC_FIELDS},
    )
    return ReferenceInstance(spec)


_SPEC_FIELDS = {
    "image",
    "label",
    "server_name",
    "ready_timeout",
    "scan_timeout",
    "poll",
}
