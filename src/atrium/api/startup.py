# SPDX-License-Identifier: GPL-3.0-or-later
"""`/Startup` - the first account, and closing the setup window.

Three of the reference's first-time-setup operations, `GetFirstUser`, `UpdateStartupUser` and
`CompleteWizard`, and nothing else of its wizard (014 spec section 2). All three sit behind
`require_setup_or_administrator`: open to this machine while setup is unfinished, and to an
administrator from anywhere (spec section 3.1, behaviours section 4.6).

**Four refusal bodies, three of the error shapes, one route.** `POST /Startup/User` answers an
absent account in problem details, a blank password as a JSON-encoded bare string, and a refused
rename as the fixed `Error processing request.` - each measured on an instance whose setup had not
run `[probe: tools/probe_first_time_setup.py, Jellyfin 10.11.11, 2026-09-13]` - and they are raised
here and nowhere else (plan section 3).

See specs/014-first-time-setup/spec.md sections 3.2 to 3.4 and plan.md sections 6.1 to 6.4.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated, Final

from fastapi import APIRouter, Depends, Request, Response

from atrium.api.deps import (
    get_passwords,
    get_paths,
    get_sessions,
    get_state,
    require_setup_or_administrator,
)
from atrium.compat.errors import NotFoundError, controller_error, message_error
from atrium.compat.model import AtriumModel
from atrium.config.paths import DataPaths
from atrium.config.state import ServerState, save
from atrium.domain.user import User
from atrium.users.first_account import (
    EmptyPasswordError,
    InvalidUsernameError,
    NoAccountError,
    StartupUserUpdate,
    UsernameTakenError,
    read_first_account,
    update_first_account,
)
from atrium.users.passwords import Passwords

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Startup"])

#: The reference's own message, byte for byte, sent as a complete JSON document: 26 characters,
#: 28 bytes on the wire `[source: Jellyfin.Api/Controllers/StartupController.cs:142 @ v10.11.11]`
#: `[probe: tools/probe_first_time_setup.py, Jellyfin 10.11.11, 2026-09-13]`.
EMPTY_PASSWORD_MESSAGE: Final = "Password must not be empty"  # noqa: S105 - a refusal, not a secret

#: What the window admits. `None` is a caller this machine sent during setup, about whom nothing
#: is known; a route must not assume one.
SetupCaller = Annotated[User | None, Depends(require_setup_or_administrator)]


class StartupUserDto(AtriumModel):
    """`[spec: StartupUserDto]` - both properties optional, both strings.

    `Password` is declared on the shape the read answers and is never answered: it is `None` there,
    and a null property is absent (behaviours section 1.7).
    """

    name: str | None = None
    password: str | None = None


@router.get("/Startup/User")
async def get_first_user(request: Request, _caller: SetupCaller) -> StartupUserDto:
    """`GetFirstUser` - **a read that writes**: the first account, created if there is none.

    Two first reads at once answer one account (plan section 6.3, `read_first_account`).
    """
    account = read_first_account(get_sessions(request))
    return StartupUserDto(name=account.name)


@router.post("/Startup/User", status_code=204)
async def update_startup_user(
    request: Request,
    _caller: SetupCaller,
    startupUserDto: StartupUserDto,  # noqa: N803 - the reference's parameter name, which a refusal names
    passwords: Annotated[Passwords, Depends(get_passwords)],
) -> Response:
    """`UpdateStartupUser` - rename the first account if asked, and set its password.

    It never creates one: a server with no account answers `404`, so the read above has to run
    first (spec section 3.3). The update hashes, so it runs off the event loop.
    """
    update = StartupUserUpdate(name=startupUserDto.name, password=startupUserDto.password)
    try:
        await asyncio.to_thread(update_first_account, get_sessions(request), passwords, update)
    except NoAccountError as exc:
        raise NotFoundError from exc
    except EmptyPasswordError:
        return message_error(400, EMPTY_PASSWORD_MESSAGE)
    except (InvalidUsernameError, UsernameTakenError):
        return controller_error(400)
    return Response(status_code=204)


@router.post("/Startup/Complete", status_code=204)
async def complete_wizard(
    _caller: SetupCaller,
    state: Annotated[ServerState, Depends(get_state)],
    paths: Annotated[DataPaths, Depends(get_paths)],
) -> Response:
    """`CompleteWizard` - close the window, checking nothing first (spec section 3.4).

    **The flag in memory moves only after the file has it.** A state file that cannot be written
    is a `500` with the window still open, and the call can simply be made again; setting the
    flag first would close a window a restart then reopens (plan section 7). A second call writes
    the same file again and answers the same `204`.
    """
    closed = state.model_copy(update={"startup_wizard_completed": True})
    save(paths, closed)
    state.startup_wizard_completed = True
    logger.info("first-time setup is finished: the setup window is closed")
    return Response(status_code=204)


__all__ = ["EMPTY_PASSWORD_MESSAGE", "StartupUserDto", "router"]
