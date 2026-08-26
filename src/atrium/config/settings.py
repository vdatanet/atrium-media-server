# SPDX-License-Identifier: GPL-3.0-or-later
"""What the operator decided.

`config.toml` is the operator's file: read at startup, never written by the server. TOML because it
is the format people can edit without a linter, and because `tomllib` is in the standard library.

The failure policy is asymmetric on purpose, and both halves matter
(specs/001-server-identity-and-discovery/plan.md section 7):

* **A missing file is normal.** Defaults, one log line saying so, carry on. A first run should work.
* **A malformed file refuses to start.** Falling back to defaults would silently ignore everything
  the operator wrote - including the published URL that makes the server reachable, and the port it
  was meant to listen on. A server that quietly runs on the wrong configuration looks healthy.
"""

from __future__ import annotations

import logging
import tomllib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from atrium.config.paths import ConfigurationError, DataPaths

logger = logging.getLogger(__name__)

DEFAULT_SERVER_NAME = "atrium"

#: The reference's port. Not a protocol requirement, and following the convention costs nothing
#: and saves every client a manual step. Two servers on one host means changing one of them.
DEFAULT_PORT = 8096


class NetworkSettings(BaseModel):
    """Everything that decides what address a client is told to use."""

    model_config = ConfigDict(extra="forbid")

    bind_address: str = "0.0.0.0"  # noqa: S104 - a media server is meant to be reachable
    port: int = Field(default=DEFAULT_PORT, ge=1, le=65535)

    #: Returned verbatim as `LocalAddress` when set. What an operator behind a reverse proxy
    #: configures, and it is never second-guessed: they know something the server does not.
    published_url: str = ""

    #: Derive the advertised address from each request's own host and scheme.
    use_request_host: bool = False


class Settings(BaseModel):
    """The whole of `config.toml`, plus the data directory it was found in."""

    model_config = ConfigDict(extra="forbid")

    #: Shown to humans. Never the discriminator a client reads - that is `ProductName`, which is
    #: fixed. See docs/compatibility/reference-target.md section 4.
    server_name: str = DEFAULT_SERVER_NAME
    network: NetworkSettings = Field(default_factory=NetworkSettings)


def _describe(error: ValidationError, path: Path) -> str:
    lines = [f"{path} is not valid:"]
    for detail in error.errors():
        key = ".".join(str(part) for part in detail["loc"]) or "(root)"
        lines.append(f"  {key}: {detail['msg']}")
    return "\n".join(lines)


def load(paths: DataPaths) -> Settings:
    """Read `config.toml`, or return defaults if there is none. Never returns partial settings."""
    path = paths.config_file

    if not path.is_file():
        logger.info(
            "no %s in %s; starting with defaults. Write one there to change anything.",
            path.name,
            paths.root,
        )
        return Settings()

    try:
        raw: dict[str, Any] = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        # tomllib's message already carries the line and column; naming the file completes it.
        raise ConfigurationError(f"{path} is not valid TOML: {exc}") from exc
    except OSError as exc:
        raise ConfigurationError(f"cannot read {path}: {exc.strerror}") from exc

    try:
        return Settings.model_validate(raw)
    except ValidationError as exc:
        # `extra="forbid"` turns a typo into an error naming the key, which is the whole point:
        # `use_request_hosts` silently ignored is a support ticket nobody can diagnose.
        raise ConfigurationError(_describe(exc, path)) from exc


__all__ = ["DEFAULT_PORT", "DEFAULT_SERVER_NAME", "NetworkSettings", "Settings", "load"]
