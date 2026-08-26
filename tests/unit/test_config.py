# SPDX-License-Identifier: GPL-3.0-or-later
"""Configuration: normal when absent, refused when wrong.

Every test here is a failure an operator actually hits - a first run, a typo, a read-only mount -
which is why they are tests rather than a paragraph in a README.
"""

from __future__ import annotations

import logging
import os
import stat
import sys
from pathlib import Path

import pytest

from atrium.config.paths import (
    DATA_DIR_ENV,
    ConfigurationError,
    DataPaths,
    default_data_dir,
    resolve_data_dir,
)
from atrium.config.settings import DEFAULT_PORT, DEFAULT_SERVER_NAME, Settings, load


@pytest.fixture
def paths(tmp_path: Path) -> DataPaths:
    prepared = DataPaths(tmp_path / "atrium")
    prepared.prepare()
    return prepared


# --------------------------------------------------------------------------------------------
# Layout
# --------------------------------------------------------------------------------------------


def test_prepare_creates_the_layout(paths: DataPaths) -> None:
    for directory in paths.directories:
        assert directory.is_dir()


def test_prepare_is_idempotent(paths: DataPaths) -> None:
    paths.config_file.write_text("server_name = 'kept'\n", encoding="utf-8")
    paths.prepare()
    assert paths.config_file.read_text(encoding="utf-8") == "server_name = 'kept'\n"


def test_prepare_leaves_nothing_behind(paths: DataPaths) -> None:
    """The writability probe writes a file; it must not still be there afterwards."""
    assert sorted(p.name for p in paths.root.iterdir()) == ["cache", "logs", "transcodes"]


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
@pytest.mark.skipif(getattr(os, "geteuid", lambda: 1)() == 0, reason="root ignores permission bits")
def test_an_unwritable_data_directory_refuses_to_start(tmp_path: Path) -> None:
    """Not a warning. Starting without somewhere to keep state means a new identity every run."""
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        with pytest.raises(ConfigurationError) as raised:
            DataPaths(locked).prepare()
        assert "not writable" in str(raised.value) or "cannot create" in str(raised.value)
        assert "server identity" in str(raised.value) or "permissions" in str(raised.value)
    finally:
        locked.chmod(stat.S_IRWXU)


def test_data_dir_precedence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(DATA_DIR_ENV, str(tmp_path / "from-env"))
    assert resolve_data_dir(tmp_path / "explicit") == (tmp_path / "explicit").resolve()
    assert resolve_data_dir() == (tmp_path / "from-env").resolve()
    monkeypatch.delenv(DATA_DIR_ENV)
    assert resolve_data_dir() == default_data_dir()


# --------------------------------------------------------------------------------------------
# Absent is normal
# --------------------------------------------------------------------------------------------


def test_a_missing_config_gives_defaults(paths: DataPaths) -> None:
    settings = load(paths)
    assert settings == Settings()
    assert settings.server_name == DEFAULT_SERVER_NAME
    assert settings.network.port == DEFAULT_PORT


def test_a_missing_config_says_so_once(paths: DataPaths, caplog: pytest.LogCaptureFixture) -> None:
    """A first run must work, and must not be silent about running on defaults."""
    with caplog.at_level(logging.INFO, logger="atrium.config.settings"):
        load(paths)
    assert len(caplog.records) == 1
    assert str(paths.root) in caplog.records[0].getMessage()


# --------------------------------------------------------------------------------------------
# Wrong is fatal
# --------------------------------------------------------------------------------------------


def test_a_valid_config_is_read(paths: DataPaths) -> None:
    paths.config_file.write_text(
        'server_name = "vdata"\n\n[network]\nport = 7920\npublished_url = "https://x"\n',
        encoding="utf-8",
    )
    settings = load(paths)
    assert settings.server_name == "vdata"
    assert settings.network.port == 7920
    assert settings.network.published_url == "https://x"
    assert settings.network.use_request_host is False


def test_malformed_toml_refuses_to_start(paths: DataPaths) -> None:
    paths.config_file.write_text("server_name = \n", encoding="utf-8")
    with pytest.raises(ConfigurationError) as raised:
        load(paths)
    message = str(raised.value)
    assert str(paths.config_file) in message, "the message names the file"
    assert "line" in message.lower(), "and where in it, so the operator can go straight there"


def test_an_out_of_range_value_refuses_to_start(paths: DataPaths) -> None:
    paths.config_file.write_text("[network]\nport = 99999\n", encoding="utf-8")
    with pytest.raises(ConfigurationError) as raised:
        load(paths)
    assert "network.port" in str(raised.value), "the message names the key"


def test_a_wrong_type_refuses_to_start(paths: DataPaths) -> None:
    paths.config_file.write_text('[network]\nport = "eight thousand"\n', encoding="utf-8")
    with pytest.raises(ConfigurationError) as raised:
        load(paths)
    assert "network.port" in str(raised.value)


def test_a_typo_in_a_key_refuses_to_start(paths: DataPaths) -> None:
    """The failure this catches is not a crash, it is a support ticket nobody can diagnose.

    `use_request_hosts` accepted and ignored means the operator's setting does nothing, the server
    looks healthy, and the only symptom is a wrong address in a response nobody thinks to read.
    """
    paths.config_file.write_text("[network]\nuse_request_hosts = true\n", encoding="utf-8")
    with pytest.raises(ConfigurationError) as raised:
        load(paths)
    assert "use_request_hosts" in str(raised.value)


def test_a_typo_at_the_top_level_refuses_to_start(paths: DataPaths) -> None:
    paths.config_file.write_text('servername = "oops"\n', encoding="utf-8")
    with pytest.raises(ConfigurationError) as raised:
        load(paths)
    assert "servername" in str(raised.value)


def test_defaults_are_never_silently_substituted_for_a_broken_file(paths: DataPaths) -> None:
    """The asymmetry, asserted: absent means defaults, malformed never does.

    Falling back would ignore everything the operator wrote - including the published URL that
    makes the server reachable at all.
    """
    paths.config_file.write_text('server_name = "x"\nport = [\n', encoding="utf-8")
    with pytest.raises(ConfigurationError):
        load(paths)
