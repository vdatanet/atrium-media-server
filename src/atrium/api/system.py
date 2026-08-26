# SPDX-License-Identifier: GPL-3.0-or-later
"""`/System` - the first request every client makes.

Three routes and two models, and the models are declared **independently rather than by
inheritance** even though one is a superset of the other. The reason is the wire: the reference
serialises `SystemInfo`'s own properties **first** and the inherited ones last, which is what a
derived .NET class does. Subclassing here would put them the other way round.

No client cares about JSON key order. A golden test comparing bytes does, and so does anything
comparing two servers' output directly - so the order is matched, and the superset relationship is
asserted by a test instead of by inheritance. That is the stronger check anyway: it fails if a
field is added to one and forgotten in the other.

See specs/001-server-identity-and-discovery/spec.md section 3.
"""

from __future__ import annotations

import platform
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from atrium import REFERENCE_PRODUCT_NAME, REFERENCE_VERSION
from atrium.api.deps import get_paths, get_settings, get_state, require_user
from atrium.compat.guids import WireGuid
from atrium.compat.model import AtriumModel
from atrium.config.paths import DataPaths
from atrium.config.settings import Settings
from atrium.config.state import ServerState
from atrium.domain.user import User
from atrium.net.address import resolve_local_address

router = APIRouter(tags=["System"])

#: `platform.machine()` speaks POSIX; the reference reports .NET's `Architecture` enum.
_ARCHITECTURES = {
    "x86_64": "X64",
    "amd64": "X64",
    "arm64": "Arm64",
    "aarch64": "Arm64",
    "i386": "X86",
    "i686": "X86",
    "armv7l": "Arm",
}


class CastReceiverApplication(AtriumModel):
    id: WireGuid | str
    name: str


class PublicSystemInfo(AtriumModel):
    """What an unauthenticated client is told. Seven fields, in the reference's order."""

    local_address: str
    server_name: str
    version: str
    product_name: str
    operating_system: str
    id: WireGuid
    startup_wizard_completed: bool


class SystemInfo(AtriumModel):
    """The authenticated superset - the reference's own properties first, inherited ones last."""

    operating_system_display_name: str
    #: Absent from the reference's own response, because it is null and nulls are omitted.
    package_name: str | None = None
    has_pending_restart: bool
    is_shutting_down: bool
    supports_library_monitor: bool
    web_socket_port_number: int
    completed_installations: list[dict[str, object]]
    can_self_restart: bool
    can_launch_web_browser: bool
    program_data_path: str
    web_path: str
    items_by_name_path: str
    cache_path: str
    log_path: str
    internal_metadata_path: str
    transcoding_temp_path: str
    cast_receiver_applications: list[CastReceiverApplication]
    has_update_available: bool
    encoder_location: str
    system_architecture: str
    local_address: str
    server_name: str
    version: str
    product_name: str
    operating_system: str
    id: WireGuid
    startup_wizard_completed: bool


def _public_fields(request: Request, settings: Settings, state: ServerState) -> dict[str, object]:
    """The seven public values, built once so the two routes cannot disagree."""
    return {
        "local_address": resolve_local_address(
            settings=settings.network,
            request_host=request.url.hostname or "",
            request_scheme=request.url.scheme,
            request_port=request.url.port,
            client_address=request.client.host if request.client else None,
        ),
        "server_name": settings.server_name,
        # The reference's version, not Atrium's: clients gate their behaviour on this string.
        # `Server:` is where this server says what it really is. reference-target.md section 4.
        "version": REFERENCE_VERSION,
        "product_name": REFERENCE_PRODUCT_NAME,
        # Always empty. The reference marks the property obsolete and never assigns it.
        "operating_system": "",
        "id": state.server_id,
        "startup_wizard_completed": state.startup_wizard_completed,
    }


@router.get("/System/Info/Public", response_model=PublicSystemInfo)
def get_public_system_info(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    state: Annotated[ServerState, Depends(get_state)],
) -> PublicSystemInfo:
    """Unauthenticated, and answerable before any user exists or any library is configured."""
    return PublicSystemInfo(**_public_fields(request, settings, state))  # type: ignore[arg-type]


@router.get("/System/Info", response_model=SystemInfo)
def get_system_info(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    state: Annotated[ServerState, Depends(get_state)],
    paths: Annotated[DataPaths, Depends(get_paths)],
    _user: Annotated[User, Depends(require_user)],
) -> SystemInfo:
    return SystemInfo(
        operating_system_display_name="",
        has_pending_restart=False,
        is_shutting_down=False,
        # The reference reports `true`; Atrium has no filesystem watcher in v1, and claiming a
        # capability it does not have would be worse than the difference. spec section 3.2.
        supports_library_monitor=False,
        web_socket_port_number=settings.network.port,
        completed_installations=[],
        can_self_restart=False,
        can_launch_web_browser=False,
        program_data_path=str(paths.root),
        web_path="",
        items_by_name_path=str(paths.root),
        cache_path=str(paths.cache),
        log_path=str(paths.logs),
        internal_metadata_path=str(paths.root),
        transcoding_temp_path=str(paths.transcodes),
        cast_receiver_applications=[],
        has_update_available=False,
        # Both properties are deprecated upstream and still populated. Matching costs nothing and
        # a client reading either learns nothing it can act on.
        encoder_location="System",
        system_architecture=_ARCHITECTURES.get(platform.machine().lower(), "X64"),
        **_public_fields(request, settings, state),  # type: ignore[arg-type]
    )


@router.get("/System/Ping", response_model=str)
@router.post("/System/Ping", response_model=str)
def ping() -> str:
    """The **product** name, not the operator's server name.

    The reference's own documentation comment says "the server name" and its code returns
    `_appHost.Name`, which is the application's product name. Following the comment instead of the
    code would return the operator's chosen name and produce a delta.
    [source: Jellyfin.Api/Controllers/SystemController.cs:102-106,
    ApplicationHost.cs:260 @ v10.11.11]
    """
    return REFERENCE_PRODUCT_NAME


__all__ = ["CastReceiverApplication", "PublicSystemInfo", "SystemInfo", "router"]
