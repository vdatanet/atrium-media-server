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
from atrium.domain.user import User


async def require_user(request: Request) -> User:
    """Resolve any of the four token mechanisms to a user, or refuse.

    Feature 002 supplies the resolution. Until then every request is refused, which is the correct
    answer for a server that cannot yet authenticate anyone: the alternative is a route that
    appears to work and is not protected.
    """
    raise UnauthenticatedError


__all__ = ["require_user"]
