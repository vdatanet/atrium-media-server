# SPDX-License-Identifier: GPL-3.0-or-later
"""Dependencies routes declare.

`require_user` is the **authentication seam**. Feature 002 owns authentication; feature 001 needs
routes that are gated by it, and inventing a credential to make them testable would ship a
mechanism no specification describes and that would outlive its purpose.

So the signature is settled now and the body is not: this version always refuses. 001's own tests
reach the authenticated path through `app.dependency_overrides`, which exercises both branches
without anything shipping.

**002 replaces the body, not the signature.** If it turns out the signature has to change, that is
a finding for 001's plan and a change to this docstring - not a quiet edit.

See specs/001-server-identity-and-discovery/plan.md section 1 and section 5.
"""

from __future__ import annotations

from starlette.requests import Request

from atrium.compat.errors import UnauthenticatedError
from atrium.config.paths import DataPaths
from atrium.config.settings import Settings
from atrium.config.state import ServerState
from atrium.domain.user import User


def get_settings(request: Request) -> Settings:
    """The operator's configuration, put on the application by its factory."""
    settings: Settings = request.app.state.settings
    return settings


def get_state(request: Request) -> ServerState:
    """The server's own record of itself, including the identity it must never regenerate."""
    state: ServerState = request.app.state.server_state
    return state


def get_paths(request: Request) -> DataPaths:
    paths: DataPaths = request.app.state.paths
    return paths


async def require_user(request: Request) -> User:
    """Resolve any of the four token mechanisms to a user, or refuse.

    Feature 002 supplies the resolution. Until then every request is refused, which is the correct
    answer for a server that cannot yet authenticate anyone: the alternative is a route that
    appears to work and is not protected.
    """
    raise UnauthenticatedError


__all__ = ["get_paths", "get_settings", "get_state", "require_user"]
