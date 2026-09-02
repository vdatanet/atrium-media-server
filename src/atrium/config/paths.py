# SPDX-License-Identifier: GPL-3.0-or-later
"""Where an Atrium instance keeps its things.

One directory holds everything an instance owns, so installing is copying a directory and a bug
report can carry its configuration. The split between the first two files is deliberate: humans
edit one and never the other, the server writes one and never the other.

    <data-dir>/
    ├── config.toml     the operator's.  Read at startup, never written by the server
    ├── state.json      the server's.    Written by the server, never edited by hand
    ├── atrium.db       the server's.    SQLite, WAL - so -wal and -shm sit beside it
    ├── cache/
    ├── logs/
    └── transcodes/

The database arrived with feature 002 and does **not** change what `state.json` is for: 001
acceptance criterion 4 forbids putting the server identity anywhere rebuildable, and a database is
rebuildable. The two files are not alternatives.

See specs/001-server-identity-and-discovery/plan.md section 4.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

#: Overrides the default location. Read once, at startup.
DATA_DIR_ENV = "ATRIUM_DATA_DIR"

CONFIG_FILE = "config.toml"
STATE_FILE = "state.json"

#: WAL mode puts `atrium.db-wal` and `atrium.db-shm` beside it while the server runs. All three
#: belong to the instance; copying the directory while it is stopped copies a consistent database.
DATABASE_FILE = "atrium.db"

#: What the server was sent and did not act on, written when the process stops (010 section 3.6,
#: D-5). **A file and never a route**: an endpoint serving it would be an endpoint Jellyfin does
#: not have (Principle I), and this is the one moment the tally is complete - after the last
#: request a route could have answered.
IGNORED_PARAMETERS_FILE = "ignored-parameters.json"


class ConfigurationError(RuntimeError):
    """The instance cannot be configured, so it must not start.

    Serving with a configuration that could not be read is worse than not serving: it looks
    healthy. See specs/001-server-identity-and-discovery/plan.md section 7.
    """


def default_data_dir() -> Path:
    """`$XDG_DATA_HOME/atrium`, or its documented fallback."""
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / "atrium"


def resolve_data_dir(explicit: Path | None = None) -> Path:
    """Command line, then environment, then the default. First one given wins."""
    if explicit is not None:
        return explicit.expanduser().resolve()
    from_env = os.environ.get(DATA_DIR_ENV)
    if from_env:
        return Path(from_env).expanduser().resolve()
    return default_data_dir()


@dataclass(frozen=True, slots=True)
class DataPaths:
    """The layout above, resolved against one root."""

    root: Path

    @property
    def config_file(self) -> Path:
        return self.root / CONFIG_FILE

    @property
    def state_file(self) -> Path:
        return self.root / STATE_FILE

    @property
    def database(self) -> Path:
        return self.root / DATABASE_FILE

    @property
    def ignored_parameters(self) -> Path:
        return self.root / IGNORED_PARAMETERS_FILE

    @property
    def cache(self) -> Path:
        return self.root / "cache"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    @property
    def transcodes(self) -> Path:
        return self.root / "transcodes"

    @property
    def artwork(self) -> Path:
        """Where artwork downloaded from a provider lands (004 plan section 6.5).

        **Under the data directory, never inside a library root.** That is the structural half of
        AC-15: a media server that writes into somebody's collection can destroy an irreplaceable
        library through one bug, and the guarantee is worth more as a place downloads *cannot*
        reach than as a rule somebody remembers.
        """
        return self.root / "metadata" / "artwork"

    @property
    def directories(self) -> tuple[Path, ...]:
        return (self.root, self.cache, self.logs, self.transcodes, self.artwork)

    def prepare(self) -> None:
        """Create what is missing and prove the root is writable, or refuse.

        The write is attempted rather than inferred from permission bits: those are only one of the
        ways a directory can be unwritable, and the others - a read-only mount, a full disk, a
        container's user mapping - are exactly the ones an operator hits and a bit-check misses.
        """
        for directory in self.directories:
            try:
                directory.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise ConfigurationError(
                    f"cannot create the data directory {directory}: {exc.strerror}. "
                    f"Set {DATA_DIR_ENV} to somewhere writable, or fix the permissions."
                ) from exc

        probe = self.root / ".atrium-write-test"
        try:
            probe.write_text("", encoding="utf-8")
            probe.unlink()
        except OSError as exc:
            raise ConfigurationError(
                f"the data directory {self.root} is not writable: {exc.strerror}. "
                f"Atrium will not start without somewhere to keep its state, because starting "
                f"without it would mean generating a new server identity on every run."
            ) from exc


__all__ = [
    "CONFIG_FILE",
    "DATABASE_FILE",
    "DATA_DIR_ENV",
    "STATE_FILE",
    "ConfigurationError",
    "DataPaths",
    "default_data_dir",
    "resolve_data_dir",
]
