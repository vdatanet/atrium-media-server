# SPDX-License-Identifier: GPL-3.0-or-later
"""`/System` at the HTTP boundary - the shape a client actually receives.

Acceptance criteria 1, 2, 3, 5, 6 and 9 of
specs/001-server-identity-and-discovery/spec.md live here.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI

from atrium import REFERENCE_PRODUCT_NAME, REFERENCE_VERSION, __version__
from atrium.compat.guids import CANONICAL
from atrium.config.state import ServerState
from atrium.domain.user import User

pytestmark = pytest.mark.conformance

PUBLIC_FIELDS = [
    "LocalAddress",
    "ServerName",
    "Version",
    "ProductName",
    "OperatingSystem",
    "Id",
    "StartupWizardCompleted",
]


# --------------------------------------------------------------------------------------------
# AC-1, AC-2, AC-3
# --------------------------------------------------------------------------------------------


async def test_public_info_answers_before_anything_is_configured(
    client: httpx.AsyncClient,
) -> None:
    """No user, no library, no token. This is the first request every client makes."""
    assert (await client.get("/System/Info/Public")).status_code == 200


async def test_public_info_has_exactly_the_seven_fields(client: httpx.AsyncClient) -> None:
    """Exactly, and in order. A field more is a delta; a field fewer breaks a client."""
    body = (await client.get("/System/Info/Public")).json()
    assert list(body) == PUBLIC_FIELDS


async def test_product_name_is_the_discriminator(client: httpx.AsyncClient) -> None:
    """The single most important string in the API.

    Multi-server clients read this to decide which dialect they are speaking. Anything else here
    sends them down an unknown-server path, and Principle I breaks at the first request.
    """
    assert (await client.get("/System/Info/Public")).json()["ProductName"] == "Jellyfin Server"


async def test_operating_system_is_the_empty_string(client: httpx.AsyncClient) -> None:
    """Not absent, not null. The reference marks the property obsolete and never assigns it, so
    its default empty string is what goes on the wire."""
    body = (await client.get("/System/Info/Public")).json()
    assert body["OperatingSystem"] == ""
    assert "OperatingSystem" in body


async def test_version_is_the_reference_version_not_atriums(client: httpx.AsyncClient) -> None:
    response = await client.get("/System/Info/Public")
    assert response.json()["Version"] == REFERENCE_VERSION
    assert response.headers["server"] == f"Atrium/{__version__}"


async def test_id_is_canonical(client: httpx.AsyncClient) -> None:
    assert CANONICAL.match((await client.get("/System/Info/Public")).json()["Id"])


async def test_id_is_the_persisted_identity(
    client: httpx.AsyncClient, server_state: ServerState
) -> None:
    assert (await client.get("/System/Info/Public")).json()["Id"] == server_state.server_id


# --------------------------------------------------------------------------------------------
# AC-6
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("method", ["get", "post"])
async def test_ping_returns_the_product_name(client: httpx.AsyncClient, method: str) -> None:
    """Not the operator's server name.

    The reference's documentation comment says "the server name"; its code returns the application
    product name. Following the comment would produce a delta.
    """
    response = await getattr(client, method)("/System/Ping")
    assert response.status_code == 200
    assert response.json() == REFERENCE_PRODUCT_NAME


async def test_ping_is_not_the_configured_server_name(client: httpx.AsyncClient) -> None:
    configured = (await client.get("/System/Info/Public")).json()["ServerName"]
    assert (await client.get("/System/Ping")).json() != configured


# --------------------------------------------------------------------------------------------
# AC-5
# --------------------------------------------------------------------------------------------


async def test_system_info_refuses_without_a_token(client: httpx.AsyncClient) -> None:
    refused = await client.get("/System/Info")
    assert refused.status_code == 401
    assert refused.content == b"", "the reference sends an empty body; behaviours 1.11"


async def test_system_info_answers_with_one(client: httpx.AsyncClient, authenticated: User) -> None:
    assert (await client.get("/System/Info")).status_code == 200


async def test_system_info_is_a_superset_that_agrees(
    client: httpx.AsyncClient, authenticated: User
) -> None:
    """The relationship the two models do not get from inheritance, asserted directly.

    They are declared independently so the wire order matches the reference - its own properties
    first, inherited ones last - which means nothing structural guarantees they agree. This does,
    and it fails if a field is added to one and forgotten in the other.
    """
    public = (await client.get("/System/Info/Public")).json()
    full = (await client.get("/System/Info")).json()
    assert set(public) <= set(full)
    assert all(full[key] == value for key, value in public.items())


async def test_system_info_puts_its_own_fields_first(
    client: httpx.AsyncClient, authenticated: User
) -> None:
    """The reference serialises a derived .NET class's own properties before the inherited ones."""
    keys = list((await client.get("/System/Info")).json())
    assert keys[0] == "OperatingSystemDisplayName"
    assert keys[-len(PUBLIC_FIELDS) :] == PUBLIC_FIELDS


async def test_system_info_omits_the_null_property(
    client: httpx.AsyncClient, authenticated: User
) -> None:
    """`PackageName` is declared and never set, and the reference omits nulls globally.

    behaviours 1.7: a single `DefaultIgnoreCondition` rather than a per-property judgement.
    """
    assert "PackageName" not in (await client.get("/System/Info")).json()


async def test_system_info_claims_no_capability_it_lacks(
    client: httpx.AsyncClient, authenticated: User
) -> None:
    """The reference reports `SupportsLibraryMonitor: true`; v1 has no watcher.

    Honest rather than faithful: a client told a capability exists behaves differently from one
    told it does not, and only one of those is recoverable.
    """
    body = (await client.get("/System/Info")).json()
    assert body["SupportsLibraryMonitor"] is False
    assert body["CanSelfRestart"] is False


# --------------------------------------------------------------------------------------------
# AC-9
# --------------------------------------------------------------------------------------------


async def test_the_profile_content_types_give_identical_bodies(client: httpx.AsyncClient) -> None:
    """The reference declares every JSON response three times, with `profile=` variants.

    All three must produce the same bytes: the body is PascalCase regardless.
    """
    bodies = {
        (await client.get("/System/Info/Public", headers={"Accept": accept})).content
        for accept in (
            "application/json",
            'application/json; profile="PascalCase"',
            'application/json; profile="CamelCase"',
        )
    }
    assert len(bodies) == 1


async def test_json_carries_the_charset(client: httpx.AsyncClient) -> None:
    response = await client.get("/System/Info/Public")
    assert response.headers["content-type"] == "application/json; charset=utf-8"


# --------------------------------------------------------------------------------------------
# The sweeps finally have something to sweep
# --------------------------------------------------------------------------------------------


def test_the_models_are_registered_for_the_sweeps(app: FastAPI) -> None:
    """Until now both sweeps passed vacuously. This is the first feature with real models."""
    from atrium.compat.registry import import_model_modules, iter_models

    import_model_modules()
    names = {model.__name__ for model in iter_models()}
    assert {"PublicSystemInfo", "SystemInfo"} <= names
