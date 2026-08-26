# SPDX-License-Identifier: GPL-3.0-or-later
"""What the server must remember and nobody should type.

`state.json` is the server's own file. It holds one thing that matters more than the rest of this
feature: the **server identity**, generated once and never again.

Acceptance criterion 4 of the specification requires that identity to survive a restart **and a
rebuild of the store from empty**. That is why it lives here and not in a database - anything in a
rebuildable store fails that requirement by construction, and a server whose identity changed would
make every client treat it as a new server and re-authenticate.

The two rules that follow from it:

* **Writes are atomic.** A crash halfway through must not cost the identity.
* **A file that cannot be read refuses to start.** Regenerating would look like a successful boot
  and silently invalidate every session in existence. The one thing this module must never do is
  invent an identity when it already had one.

See specs/001-server-identity-and-discovery/plan.md section 4.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, ValidationError

from atrium.compat.dates import from_wire, utc_now
from atrium.compat.guids import WireGuid, new_id
from atrium.config.paths import ConfigurationError, DataPaths

logger = logging.getLogger(__name__)


class ServerState(BaseModel):
    """The server's own record of itself.

    `extra="allow"` is deliberate. A newer Atrium may write keys this version does not know, and a
    downgrade must hand them back untouched rather than quietly dropping them - losing a newer
    version's state is a data-loss bug that only shows up after someone has already downgraded to
    escape a different problem.
    """

    model_config = ConfigDict(extra="allow")

    #: `WireGuid` rather than a bare string with a pattern: one definition of what an identifier
    #: is, and it carries the error message that says so in words rather than in a regex.
    server_id: WireGuid
    startup_wizard_completed: bool = False
    #: Parsed leniently and always stored aware. This file is the server's own, not the wire, so
    #: it is written in plain ISO 8601 rather than the reference's seven-digit format.
    created: Annotated[datetime, BeforeValidator(from_wire)]


def _write_atomically(path: Path, payload: str) -> None:
    """Write, flush, fsync, rename - so the file is either the old one or the new one.

    The temporary file sits in the same directory as the target, because `os.replace` is only
    atomic within a filesystem and a temp directory may be on another one.
    """
    temporary = path.with_name(f"{path.name}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    except OSError:
        temporary.unlink(missing_ok=True)
        raise

    if sys.platform != "win32":
        # Rename durability is a property of the directory, not of the file: without this, a power
        # loss can leave the rename un-recorded even though the data was synced.
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)


def save(paths: DataPaths, state: ServerState) -> None:
    try:
        _write_atomically(paths.state_file, json.dumps(state.model_dump(mode="json"), indent=1))
    except OSError as exc:
        raise ConfigurationError(
            f"cannot write {paths.state_file}: {exc.strerror}. Atrium will not continue without "
            f"being able to record its identity."
        ) from exc


def load_or_create(paths: DataPaths) -> ServerState:
    """Read the state, or create it on a first run. Never silently replaces an unreadable one."""
    path = paths.state_file

    if not path.is_file():
        state = ServerState(server_id=new_id(), created=utc_now())
        save(paths, state)
        logger.info("first start: this server's identity is %s", state.server_id)
        return state

    try:
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigurationError(
            f"{path} is not readable JSON: {exc}. Atrium will not start, because generating a new "
            f"identity would make every client treat this as a different server and re-"
            f"authenticate. Restore the file from a backup, or delete it to accept that cost."
        ) from exc
    except OSError as exc:
        raise ConfigurationError(f"cannot read {path}: {exc.strerror}") from exc

    try:
        return ServerState.model_validate(raw)
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(str(p) for p in d['loc']) or '(root)'}: {d['msg']}" for d in exc.errors()
        )
        raise ConfigurationError(
            f"{path} is not valid server state ({details}). Atrium will not start rather than "
            f"replace it: see the message above about identity."
        ) from exc


__all__ = ["ServerState", "load_or_create", "save"]
