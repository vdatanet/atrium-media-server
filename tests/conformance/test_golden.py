# SPDX-License-Identifier: GPL-3.0-or-later
"""The three `/System` responses, byte for byte.

Acceptance criteria 1, 2, 3, 6 and 9 of specs/001-server-identity-and-discovery/spec.md, asserted
against checked-in bytes rather than against a parsed document. The other tests in this directory
assert what a field *means*; these assert what a client's socket *receives*, which is where
casing, `null`-versus-absent and integer-versus-string live.

**The instance is pinned, not normalised.** Three values would otherwise differ between two hosts
running the same code, and each is fixed at its source instead of being substituted out of the
answer afterwards:

**`Id`** - pinned by a `state.json` written before the server starts. The identity is read from a
file, so the file is the honest place to fix it, and the golden then shows a real identifier in a
real position.

**`LocalAddress`** - pinned by `use_request_host`, which derives the address from the request. The
default tier asks the routing table, and that answers differently on every machine; this tier is a
function of the request alone.

**`SystemArchitecture`** - pinned by fixing what `platform.machine()` reports. Substituting the
result would hide the mapping between POSIX's names and the reference's, which is the only part
that can be wrong. It gets its own test at the bottom of this file instead.

That leaves exactly one substitution - the temporary data directory - and it is unavoidable: the
paths are real paths, and they are different on every run.
"""

from __future__ import annotations

import json
import platform
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from atrium.api.deps import require_user
from atrium.api.system import _ARCHITECTURES
from atrium.compat.responses import JSON_MEDIA_TYPE
from atrium.config.paths import DataPaths
from atrium.domain.user import User
from atrium.server import create_app
from tests.conformance.golden import assert_golden
from tests.conftest import TEST_USER

pytestmark = pytest.mark.conformance

#: The identifier the golden instance is born with. The example from `atrium.compat.guids`, so the
#: project has one fixture identity rather than one per test that needed a plausible string.
GOLDEN_SERVER_ID = "0d41983a5d18d53282f56e7460e2c2cd"

#: What `platform.machine()` reports for the golden run. The reference's own `Architecture` names
#: are what reaches the wire; the mapping between the two is asserted separately.
GOLDEN_MACHINE = "x86_64"

#: Substituted in the body before comparison, because a temporary directory is different every run.
DATA_DIR_PLACEHOLDER = "{data-dir}"

CONFIG = """\
# Written by the golden fixture. See the module docstring for what each line pins.
server_name = "atrium"

[network]
port = 8096
use_request_host = true
"""

STATE = {
    "server_id": GOLDEN_SERVER_ID,
    "startup_wizard_completed": False,
    "created": "2026-08-26T00:00:00+00:00",
}

PROFILES = [
    "application/json",
    'application/json; profile="PascalCase"',
    'application/json; profile="CamelCase"',
]


@pytest.fixture
def golden_paths(tmp_path: Path) -> DataPaths:
    """A data directory whose configuration and identity are decided before the server reads it."""
    paths = DataPaths(tmp_path / "atrium")
    paths.prepare()
    paths.config_file.write_text(CONFIG, encoding="utf-8")
    paths.state_file.write_text(json.dumps(STATE, indent=1), encoding="utf-8")
    return paths


@pytest.fixture
def golden_app(golden_paths: DataPaths, monkeypatch: pytest.MonkeyPatch) -> Iterator[FastAPI]:
    monkeypatch.setattr(platform, "machine", lambda: GOLDEN_MACHINE)
    built = create_app(golden_paths)
    built.state.readiness.mark_ready()
    yield built
    built.dependency_overrides.clear()


@pytest.fixture
async def golden_client(golden_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=golden_app, client=("192.168.1.50", 51234))
    async with httpx.AsyncClient(transport=transport, base_url="http://atrium:8096") as opened:
        yield opened


@pytest.fixture
def golden(
    request: pytest.FixtureRequest, golden_paths: DataPaths
) -> Callable[[str, httpx.Response], bytes]:
    """Compare a response to `tests/golden/<name>.json`."""

    def check(name: str, response: httpx.Response) -> bytes:
        return assert_golden(
            name,
            response,
            config=request.config,
            placeholders={str(golden_paths.root): DATA_DIR_PLACEHOLDER},
        )

    return check


@pytest.fixture
def golden_authenticated(golden_app: FastAPI) -> User:
    golden_app.dependency_overrides[require_user] = lambda: TEST_USER
    return TEST_USER


# --------------------------------------------------------------------------------------------
# The three endpoints
# --------------------------------------------------------------------------------------------


async def test_public_system_info(
    golden_client: httpx.AsyncClient, golden: Callable[[str, httpx.Response], bytes]
) -> None:
    """AC-1, AC-2, AC-3. The first request every client makes, to the byte."""
    response = await golden_client.get("/System/Info/Public")
    assert response.status_code == 200
    assert response.headers["content-type"] == JSON_MEDIA_TYPE
    golden("System.Info.Public", response)


async def test_system_info(
    golden_client: httpx.AsyncClient,
    golden: Callable[[str, httpx.Response], bytes],
    golden_authenticated: User,
) -> None:
    """The authenticated superset, including the field the reference declares and omits."""
    response = await golden_client.get("/System/Info")
    assert response.status_code == 200
    body = golden("System.Info", response)
    assert b"PackageName" not in body, "a null property is absent, not null: behaviours 1.7"


async def test_ping(
    golden_client: httpx.AsyncClient, golden: Callable[[str, httpx.Response], bytes]
) -> None:
    """AC-6. A bare JSON string, quotes and all - not an object, not a bare word."""
    response = await golden_client.get("/System/Ping")
    assert response.status_code == 200
    golden("System.Ping", response)


async def test_ping_answers_both_methods_identically(golden_client: httpx.AsyncClient) -> None:
    """AC-6, the other half. One golden covers both because the bytes are the same bytes."""
    got = await golden_client.get("/System/Ping")
    posted = await golden_client.post("/System/Ping")
    assert posted.content == got.content
    assert posted.headers["content-type"] == got.headers["content-type"]


# --------------------------------------------------------------------------------------------
# AC-9 - the content-type variants
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("accept", PROFILES)
async def test_every_profile_gets_the_pascal_case_golden(
    golden_client: httpx.AsyncClient,
    golden: Callable[[str, httpx.Response], bytes],
    accept: str,
) -> None:
    """AC-9. All three declared content types receive the same bytes from Atrium.

    Two of those three are the contract. The third is a **known gap**: the reference answers
    `profile="CamelCase"` with camelCase property names, and Atrium does not implement the profile
    yet. See the test below, which is the one that fails the day it does.
    """
    response = await golden_client.get("/System/Info/Public", headers={"Accept": accept})
    assert response.status_code == 200
    golden("System.Info.Public", response)


async def test_the_camel_case_profile_is_a_known_gap(golden_client: httpx.AsyncClient) -> None:
    """Pinning a difference Atrium has not closed yet, so that closing it is noticed.

    The reference answers `Accept: application/json; profile="CamelCase"` with camelCase property
    names and echoes the matched profile in its own content type.
    [probe: tools/probe_content_type_profiles.py, Jellyfin 10.11.11, 2026-08-26]
    Atrium answers PascalCase with a plain content type, which is
    docs/compatibility/behaviours.md section 5's gap and task T19's job.

    When T19 lands, this test fails - and its failure is the reminder to record the second golden
    and delete this. That is the point of writing it down as a test rather than as a comment.
    """
    response = await golden_client.get(
        "/System/Info/Public", headers={"Accept": 'application/json; profile="CamelCase"'}
    )
    body = response.json()
    assert "LocalAddress" in body, "still PascalCase: behaviours 1.13, closed by 001 T19"
    assert "localAddress" not in body
    assert response.headers["content-type"] == JSON_MEDIA_TYPE, "the profile is not echoed yet"


# --------------------------------------------------------------------------------------------
# What pinning the host costs
# --------------------------------------------------------------------------------------------


def test_the_architecture_mapping_covers_what_a_host_reports() -> None:
    """The golden fixes `platform.machine()`, so the mapping needs asserting somewhere else.

    Substituting `SystemArchitecture` out of the golden instead would have hidden exactly this:
    the values are the reference's .NET `Architecture` names, not POSIX's, and the difference is
    invisible until a client reads one.
    """
    assert {_ARCHITECTURES[name] for name in ("x86_64", "amd64")} == {"X64"}
    assert {_ARCHITECTURES[name] for name in ("arm64", "aarch64")} == {"Arm64"}
    assert _ARCHITECTURES["armv7l"] == "Arm"
    assert all(name == name.lower() for name in _ARCHITECTURES), (
        "the lookup is done on a lowercased value, so an uppercase key would never match"
    )
    assert _ARCHITECTURES[GOLDEN_MACHINE] == "X64", "what the golden file records"
