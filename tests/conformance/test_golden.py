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
from atrium.compat.profiles import Profile
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


async def test_cultures(
    golden_client: httpx.AsyncClient,
    golden: Callable[[str, httpx.Response], bytes],
    golden_authenticated: User,
) -> None:
    """004 AC: `GET /Localization/Cultures` reaches L2 - the whole list, to the byte.

    The table is generated from a measurement of the reference
    `[probe: tools/generate_cultures.py, Jellyfin 10.11.11, 2026-08-27]`, so this file is the
    contract: a regeneration that added, dropped or reordered a language shows up here as a diff
    somebody has to look at, which is the point of a golden rather than a count.
    """
    response = await golden_client.get("/Localization/Cultures")
    assert response.status_code == 200
    assert response.headers["content-type"] == JSON_MEDIA_TYPE
    body = golden("Localization.Cultures", response)
    assert b'"ThreeLetterISOLanguageNames":["fra","fre"]' in body, (
        "the terminological code comes first; a client reads the first entry"
    )


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


@pytest.mark.parametrize("accept", [PROFILES[0], PROFILES[1]])
async def test_the_pascal_case_profiles_get_the_pascal_case_golden(
    golden_client: httpx.AsyncClient,
    golden: Callable[[str, httpx.Response], bytes],
    accept: str,
) -> None:
    """AC-9, first half. `application/json` and `profile="PascalCase"` are the same bytes."""
    response = await golden_client.get("/System/Info/Public", headers={"Accept": accept})
    assert response.status_code == 200
    golden("System.Info.Public", response)


async def test_the_camel_case_profile_gets_its_own_golden(
    golden_client: httpx.AsyncClient, golden: Callable[[str, httpx.Response], bytes]
) -> None:
    """AC-9, second half. A different serialisation, so a different file.

    Two goldens for one response is the honest shape: they are two contracts, and a client that
    asks for the second and receives the first gets an empty object out of its decoder.
    [probe: tools/probe_content_type_profiles.py, Jellyfin 10.11.11, 2026-08-26]
    """
    response = await golden_client.get("/System/Info/Public", headers={"Accept": PROFILES[2]})
    assert response.status_code == 200
    golden("System.Info.Public.CamelCase", response)


@pytest.mark.parametrize(
    ("accept", "content_type"),
    [
        (PROFILES[0], JSON_MEDIA_TYPE),
        (PROFILES[1], 'application/json; profile="PascalCase"; charset=utf-8'),
        (PROFILES[2], 'application/json; profile="CamelCase"; charset=utf-8'),
    ],
)
async def test_the_response_echoes_the_profile_that_matched(
    golden_client: httpx.AsyncClient, accept: str, content_type: str
) -> None:
    """The profile comes back in the content type, before the charset, canonically spelled."""
    response = await golden_client.get("/System/Info/Public", headers={"Accept": accept})
    assert response.headers["content-type"] == content_type


async def test_the_two_serialisations_carry_the_same_values(
    golden_client: httpx.AsyncClient,
) -> None:
    """Different names, identical content. Anything else would be two APIs, not two spellings."""
    pascal = (await golden_client.get("/System/Info/Public")).json()
    camel = (await golden_client.get("/System/Info/Public", headers={"Accept": PROFILES[2]})).json()
    assert list(camel) == [name[:1].lower() + name[1:] for name in pascal]
    assert list(camel.values()) == list(pascal.values())


async def test_a_bare_string_body_echoes_the_profile_too(golden_client: httpx.AsyncClient) -> None:
    """`/System/Ping` has no property names, and the reference still echoes the profile on it."""
    response = await golden_client.get("/System/Ping", headers={"Accept": PROFILES[2]})
    assert response.content == b'"Jellyfin Server"'
    assert response.headers["content-type"] == Profile.CAMEL.media_type


async def test_a_refusal_echoes_nothing(golden_client: httpx.AsyncClient) -> None:
    """An empty 401 carries no content type in the reference, so there is nothing to echo."""
    response = await golden_client.get("/System/Info", headers={"Accept": PROFILES[2]})
    assert response.status_code == 401
    assert "content-type" not in response.headers


async def test_two_requests_do_not_share_a_profile(golden_client: httpx.AsyncClient) -> None:
    """The negotiated profile lives in a context variable, and a context variable can leak.

    Interleaved so that a leak shows: camelCase, then plain, then camelCase again.
    """
    first = await golden_client.get("/System/Info/Public", headers={"Accept": PROFILES[2]})
    plain = await golden_client.get("/System/Info/Public")
    again = await golden_client.get("/System/Info/Public", headers={"Accept": PROFILES[2]})
    assert b'"localAddress"' in first.content
    assert b'"LocalAddress"' in plain.content
    assert again.content == first.content


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
