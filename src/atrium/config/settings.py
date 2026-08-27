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


class PasswordSettings(BaseModel):
    """What verifying a password costs, per ADR-0006.

    The defaults are **RFC 9106's low-memory profile**, written out here rather than taken from
    argon2-cffi's own defaults: a library default can move under a project without anybody
    deciding it should, and these are a security parameter. A test ties them to the library's
    profile, so a drift in either direction is visible rather than silent.

    They are safe to raise. A record carries the parameters it was made with, and a password that
    verifies against an out-of-date record is rewritten with the current ones at the one moment the
    plaintext exists - which is what lets these move without a mass reset.

    Lowering them is what a test suite does, and only a test suite: verifying dozens of passwords
    at 64 MiB takes minutes, and a slow suite gets run less often, which costs more security than
    the parameters buy (plan section 8.4).
    """

    model_config = ConfigDict(extra="forbid")

    #: KiB. 65536 is 64 MiB.
    memory_cost: int = Field(default=65536, ge=8)
    time_cost: int = Field(default=3, ge=1)
    parallelism: int = Field(default=4, ge=1)


class AuthenticationSettings(BaseModel):
    """What the operator decides about logging in.

    **`lockout_attempts` defaults to 0, which is no lockout at all**, and that is a deliberate
    reading of an unmeasured value rather than an absence of one. The reference sends
    `LoginAttemptsBeforeLockout = -1` for an untouched account - a sentinel, not a count (spec
    section 7, OQ-6) - and what -1 means there has not been measured, because measuring it means
    locking a real account on somebody's own server.

    Until it is, an account whose policy carries a sentinel is not locked. The direction is chosen:
    locking somebody out of their own server on a guess is a failure they experience and cannot
    undo, while not locking is invisible to every client and becomes correct the moment OQ-6 is
    answered. An operator who wants it sets a number here, and a policy carrying a positive
    `LoginAttemptsBeforeLockout` is honoured whatever this says.
    """

    model_config = ConfigDict(extra="forbid")

    #: Used when a user's own policy carries a sentinel rather than a count. 0 disables lockout.
    lockout_attempts: int = Field(default=0, ge=0)


class ProviderSettings(BaseModel):
    """What an operator configured for the online metadata providers (004 spec section 3.5).

    **Empty is the normal case and not an error.** A provider with no credentials sits out with a
    reason, everything local still works, and the scan report says which ones were disabled
    (AC-9): a v1 install with no internet must produce a usable library.

    The credentials are the operator's, so they live in the operator's file rather than in the
    database - which also means a leaked backup of the library contains no keys.
    """

    #: TMDB's API key. Without it, films and series resolve from sidecars, tags and paths alone.
    tmdb_api_key: str = ""

    #: An email address or URL. MusicBrainz **requires** an identifying `User-Agent` and refuses
    #: traffic without one, so this is that provider's credential even though it is not a secret
    #: (004 plan section 6.6).
    musicbrainz_contact: str = ""

    #: The country whose certification becomes `official_rating` for a film (plan section 6.5).
    #: Two letters, the reference's own default.
    metadata_country: str = "US"


class Settings(BaseModel):
    """The whole of `config.toml`, plus the data directory it was found in."""

    model_config = ConfigDict(extra="forbid")

    #: Shown to humans. Never the discriminator a client reads - that is `ProductName`, which is
    #: fixed. See docs/compatibility/reference-target.md section 4.
    server_name: str = DEFAULT_SERVER_NAME
    network: NetworkSettings = Field(default_factory=NetworkSettings)
    passwords: PasswordSettings = Field(default_factory=PasswordSettings)
    authentication: AuthenticationSettings = Field(default_factory=AuthenticationSettings)
    providers: ProviderSettings = Field(default_factory=ProviderSettings)


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


__all__ = [
    "DEFAULT_PORT",
    "DEFAULT_SERVER_NAME",
    "AuthenticationSettings",
    "NetworkSettings",
    "PasswordSettings",
    "ProviderSettings",
    "Settings",
    "load",
]
