# SPDX-License-Identifier: GPL-3.0-or-later
"""The seven feature 002 responses, byte for byte.

The other tests in this directory assert what a field *means*. These assert what a client's socket
receives, which is where casing, `null`-versus-absent, integer-versus-string and **field order**
live - and field order is the one this feature got wrong twice before it was measured.

**Pinned, not normalised.** The harness's rule is that a placeholder exists because a value is
unstable, never because it is inconvenient, so:

* the **server identity** is written into `state.json` before the server starts, as 001 does;
* the **user** is created with a fixed identifier, a fixed name and a fixed configuration;
* the **dates** are written after authenticating and before reading, so two of these seven goldens
  need no placeholder at all.

Three values remain genuinely unstable and are substituted: the **access token** and the **session
identifier**, which are random by construction and would be useless if they were not, and the
**timestamps** in the two responses that report them as they happen.

**What a placeholder gives up, an assertion takes back.** A substituted value cannot fail a format
check, so each one is checked *before* it is replaced: 32 lowercase hex for the token and the
session, and seven fractional digits with a `Z` for a date. Otherwise `AccessToken` could become an
integer and the golden would still pass.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator, Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from atrium.compat.guids import CANONICAL
from atrium.config.paths import DataPaths
from atrium.db.repositories import UserRepository
from atrium.domain.user import LibraryAccess, User
from atrium.server import create_app
from tests.conformance.golden import assert_golden
from tests.conformance.test_golden import STATE

pytestmark = pytest.mark.conformance

PASSWORD = "correct horse battery staple"
GOLDEN_USER_ID = "b7c1d5e9f3a24b6c8d0e2f4a6b8c0d1e"
GOLDEN_DEVICE = "golden-device-0001"
CLIENT_HEADER = (
    'MediaBrowser Client="Atrium Golden", Device="Bench", '
    f'DeviceId="{GOLDEN_DEVICE}", Version="1.0"'
)

#: Written after authenticating and before reading, so the two goldens that report them are pinned.
GOLDEN_LOGIN = datetime(2026, 8, 26, 9, 30, tzinfo=UTC)
GOLDEN_ACTIVITY = datetime(2026, 8, 26, 9, 31, tzinfo=UTC)

TOKEN_PLACEHOLDER = "{access-token}"
SESSION_PLACEHOLDER = "{session-id}"
DATE_PLACEHOLDER = "{date}"

#: The reference's date format: seven fractional digits and a `Z`. Asserted before substitution.
WIRE_DATE = re.compile(r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{7}Z\Z")

CONFIG = """\
# Written by the golden fixture. Argon2 at its cheapest, because a golden run should not spend
# forty milliseconds per hash for bytes that do not contain one.
server_name = "atrium"

[network]
port = 8096
use_request_host = true

[passwords]
memory_cost = 8
time_cost = 1
parallelism = 1
"""

#: A configuration a client posted, including a property v1 does not act on. Fixed, so the golden
#: shows a real document rather than an empty object.
GOLDEN_CONFIGURATION = {
    "AudioLanguagePreference": "cat",
    "DisplayMissingEpisodes": True,
    "SubtitleMode": "Smart",
    "RememberAudioSelections": False,
    "SomethingFromANewerServer": {"nested": [1, 2]},
}

#: The two honoured list properties, so the join table reaches the wire in a golden.
GOLDEN_LIBRARY = "a" * 32


@pytest.fixture
def golden_paths(tmp_path: Path) -> DataPaths:
    paths = DataPaths(tmp_path / "atrium")
    paths.prepare()
    paths.config_file.write_text(CONFIG, encoding="utf-8")
    paths.state_file.write_text(json.dumps(STATE, indent=1), encoding="utf-8")
    return paths


@pytest.fixture
def golden_app(golden_paths: DataPaths) -> Iterator[FastAPI]:
    built = create_app(golden_paths)
    built.state.readiness.mark_ready()
    with built.state.sessions.begin() as opened:
        users = UserRepository(opened)
        users.add(
            User(
                id=GOLDEN_USER_ID,
                name="Joan",
                password_hash=built.state.passwords.hash(PASSWORD),
                configuration=dict(GOLDEN_CONFIGURATION),
                policy_extra={"EnableRemoteAccess": True, "SyncPlayAccess": "CreateAndJoinGroups"},
            )
        )
        users.set_library_access(GOLDEN_USER_ID, LibraryAccess(enabled_folders=(GOLDEN_LIBRARY,)))
    yield built
    built.dependency_overrides.clear()


@pytest.fixture
async def golden_client(golden_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=golden_app, client=("192.168.1.50", 51234))
    async with httpx.AsyncClient(transport=transport, base_url="http://atrium:8096") as opened:
        yield opened


def pin_dates(app: FastAPI) -> None:
    """Fix the two timestamps the user object reports, after they have been set by logging in."""
    with app.state.sessions.begin() as opened:
        UserRepository(opened).record_success(GOLDEN_USER_ID, when=GOLDEN_LOGIN)
        row = opened.get(__import__("atrium.db.models", fromlist=["User"]).User, GOLDEN_USER_ID)
        assert row is not None
        row.last_activity_date = GOLDEN_ACTIVITY


@pytest.fixture
async def token(golden_client: httpx.AsyncClient, golden_app: FastAPI) -> str:
    answered = await golden_client.post(
        "/Users/AuthenticateByName",
        json={"Username": "Joan", "Pw": PASSWORD},
        headers={"X-Emby-Authorization": CLIENT_HEADER},
    )
    assert answered.status_code == 200
    issued: str = answered.json()["AccessToken"]
    return issued


@pytest.fixture
def golden(request: pytest.FixtureRequest) -> Callable[..., bytes]:
    def check(name: str, response: httpx.Response, **placeholders: str) -> bytes:
        return assert_golden(
            name, response, config=request.config, placeholders=placeholders or None
        )

    return check


def check_unstable(body: dict[str, object], token: str = "", session_id: str = "") -> None:
    """Assert the format of every value about to be replaced by a placeholder.

    A substituted value cannot fail a comparison, so this is what a placeholder costs and this is
    it being paid back: `AccessToken` could become an integer, or a date could lose its fractional
    digits, and the golden would not notice.
    """
    if token:
        assert CANONICAL.match(token), f"the token is not 32 lowercase hex: {token!r}"
    if session_id:
        assert CANONICAL.match(session_id), "the session id is not 32 lowercase hex"

    def walk(value: object) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if isinstance(item, str) and str(key).endswith(("Date", "CheckIn")):
                    assert WIRE_DATE.match(item), f"{key} is not a wire date: {item}"
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(body)


# --------------------------------------------------------------------------------------------
# The two that need no placeholder at all
# --------------------------------------------------------------------------------------------


async def test_public_users(
    golden_app: FastAPI, golden_client: httpx.AsyncClient, golden: Callable[..., bytes]
) -> None:
    """Unauthenticated, so there is no token in it, and every value is pinned.

    It carries `Configuration` and `Policy`, which is what the reference does and the opposite of
    what this feature's specification asserted until it was measured (behaviours section 3.5).
    """
    pin_dates(golden_app)
    answered = await golden_client.get("/Users/Public")
    assert answered.status_code == 200
    golden("Users.Public", answered)


async def test_current_user(
    golden_app: FastAPI, golden_client: httpx.AsyncClient, token: str, golden: Callable[..., bytes]
) -> None:
    """The token is in the header, not the body, so this one is pinned too."""
    pin_dates(golden_app)
    answered = await golden_client.get("/Users/Me", headers={"X-Emby-Token": token})
    assert answered.status_code == 200
    golden("Users.Me", answered)


async def test_current_user_under_the_camel_case_profile(
    golden_app: FastAPI, golden_client: httpx.AsyncClient, token: str, golden: Callable[..., bytes]
) -> None:
    """The profile reaches **inside** `Policy` and `Configuration`.

    Those are mappings here and objects on the reference, so without the `PropertyKeyed` marker
    every one of their properties would be PascalCase where the reference sends camelCase. This is
    the golden that would have caught it.
    """
    pin_dates(golden_app)
    answered = await golden_client.get(
        "/Users/Me",
        headers={"X-Emby-Token": token, "Accept": 'application/json; profile="CamelCase"'},
    )
    assert answered.status_code == 200
    golden("Users.Me.CamelCase", answered)


async def test_user_by_id(
    golden_app: FastAPI, golden_client: httpx.AsyncClient, token: str, golden: Callable[..., bytes]
) -> None:
    """The project's first parameterised route, reading the caller's own account."""
    pin_dates(golden_app)
    answered = await golden_client.get(f"/Users/{GOLDEN_USER_ID}", headers={"X-Emby-Token": token})
    assert answered.status_code == 200
    golden("Users.ById", answered)


# --------------------------------------------------------------------------------------------
# The three that report values generated as they happen
# --------------------------------------------------------------------------------------------


async def test_authenticate_by_name(
    golden_client: httpx.AsyncClient, golden: Callable[..., bytes]
) -> None:
    answered = await golden_client.post(
        "/Users/AuthenticateByName",
        json={"Username": "Joan", "Pw": PASSWORD},
        headers={"X-Emby-Authorization": CLIENT_HEADER},
    )
    assert answered.status_code == 200
    body = answered.json()
    check_unstable(body, token=body["AccessToken"], session_id=body["SessionInfo"]["Id"])

    dates = {
        body["SessionInfo"]["LastActivityDate"]: DATE_PLACEHOLDER,
        body["User"]["LastLoginDate"]: DATE_PLACEHOLDER,
        body["User"]["LastActivityDate"]: DATE_PLACEHOLDER,
    }
    golden(
        "Users.AuthenticateByName",
        answered,
        **{body["AccessToken"]: TOKEN_PLACEHOLDER, body["SessionInfo"]["Id"]: SESSION_PLACEHOLDER},
        **dates,
    )


async def test_sessions(
    golden_client: httpx.AsyncClient, token: str, golden: Callable[..., bytes]
) -> None:
    answered = await golden_client.get("/Sessions", headers={"X-Emby-Token": token})
    assert answered.status_code == 200
    [entry] = answered.json()
    check_unstable(entry, session_id=entry["Id"])
    golden(
        "Sessions",
        answered,
        **{entry["Id"]: SESSION_PLACEHOLDER, entry["LastActivityDate"]: DATE_PLACEHOLDER},
    )


# --------------------------------------------------------------------------------------------
# The two that answer with nothing, which is itself a contract
# --------------------------------------------------------------------------------------------


async def test_update_configuration_answers_with_no_body(
    golden_client: httpx.AsyncClient, token: str, golden: Callable[..., bytes]
) -> None:
    """A `204` with a body would be a difference a client can see, and an empty golden says so."""
    answered = await golden_client.post(
        "/Users/Configuration",
        json=dict(GOLDEN_CONFIGURATION),
        headers={"X-Emby-Token": token},
    )
    assert answered.status_code == 204
    golden("Users.Configuration", answered)


async def test_post_capabilities_answers_with_no_body(
    golden_client: httpx.AsyncClient, token: str, golden: Callable[..., bytes]
) -> None:
    answered = await golden_client.post(
        "/Sessions/Capabilities/Full",
        json={"PlayableMediaTypes": ["Video"], "SupportedCommands": ["Play"]},
        headers={"X-Emby-Token": token},
    )
    assert answered.status_code == 204
    golden("Sessions.Capabilities.Full", answered)
