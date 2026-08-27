# SPDX-License-Identifier: GPL-3.0-or-later
"""Server identity: generated once, written atomically, never silently replaced."""

from __future__ import annotations

import json
import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from atrium.compat.guids import CANONICAL
from atrium.config.paths import ConfigurationError, DataPaths
from atrium.config.state import ServerState, load_or_create, save


@pytest.fixture
def paths(tmp_path: Path) -> DataPaths:
    prepared = DataPaths(tmp_path / "atrium")
    prepared.prepare()
    return prepared


# --------------------------------------------------------------------------------------------
# Acceptance criterion 4
# --------------------------------------------------------------------------------------------


def test_identity_is_canonical(paths: DataPaths) -> None:
    assert CANONICAL.match(load_or_create(paths).server_id)


def test_identity_survives_a_restart(paths: DataPaths) -> None:
    assert load_or_create(paths).server_id == load_or_create(paths).server_id


def test_identity_survives_a_rebuild_of_the_store_from_empty(paths: DataPaths) -> None:
    """Acceptance criterion 4, third phase - and the reason this module exists.

    Everything except `state.json` is deleted, as a store rebuild would leave it, and the identity
    must be unchanged.

    **This passes trivially today, because there is no store.** That is exactly why it is written
    now: feature 002 introduces a database, and the moment someone moves the identity into it for
    tidiness, this test is what says no. A test added afterwards would be a test written to fit
    whatever the code had already done.
    """
    original = load_or_create(paths).server_id

    # `shutil.rmtree` rather than one level of `iterdir`, since 004 T12: the layout gained
    # `metadata/artwork`, which is two deep, and a rebuild deletes a tree rather than a directory.
    for entry in paths.root.iterdir():
        if entry.name == paths.state_file.name:
            continue
        if entry.is_dir():
            shutil.rmtree(entry)
        else:
            entry.unlink()
    paths.prepare()

    assert load_or_create(paths).server_id == original


def test_first_start_says_what_the_identity_is(
    paths: DataPaths, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="atrium.config.state"):
        state = load_or_create(paths)
    assert state.server_id in caplog.records[0].getMessage()


# --------------------------------------------------------------------------------------------
# Never silently replaced
# --------------------------------------------------------------------------------------------


def test_corrupt_json_refuses_to_start(paths: DataPaths) -> None:
    """Not "regenerate and carry on". That would look like a successful boot."""
    load_or_create(paths)
    paths.state_file.write_text("{ this is not json", encoding="utf-8")
    with pytest.raises(ConfigurationError) as raised:
        load_or_create(paths)
    message = str(raised.value)
    assert "re-authenticate" in message, "the message says what regenerating would cost"
    assert "backup" in message, "and what the operator can do about it"


def test_an_invalid_identity_refuses_to_start(paths: DataPaths) -> None:
    paths.state_file.write_text(
        json.dumps({"server_id": "nope", "created": "2026-01-01T00:00:00Z"}), encoding="utf-8"
    )
    with pytest.raises(ConfigurationError):
        load_or_create(paths)


def test_a_corrupt_file_is_left_alone(paths: DataPaths) -> None:
    """Refusing to start must not also destroy the evidence a backup could be compared against."""
    load_or_create(paths)
    paths.state_file.write_text("{ broken", encoding="utf-8")
    with pytest.raises(ConfigurationError):
        load_or_create(paths)
    assert paths.state_file.read_text(encoding="utf-8") == "{ broken"


# --------------------------------------------------------------------------------------------
# Atomicity
# --------------------------------------------------------------------------------------------


def test_an_interrupted_write_leaves_the_previous_file_intact(
    paths: DataPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The crash this protects against: power loss between writing and renaming."""
    original = load_or_create(paths)
    before = paths.state_file.read_text(encoding="utf-8")

    def explode(*_args: object, **_kwargs: object) -> None:
        raise OSError(5, "Input/output error")

    monkeypatch.setattr(Path, "replace", explode)
    with pytest.raises(ConfigurationError):
        save(paths, original)

    assert paths.state_file.read_text(encoding="utf-8") == before


def test_an_interrupted_write_leaves_no_temporary_file(
    paths: DataPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = load_or_create(paths)

    def explode(*_args: object, **_kwargs: object) -> None:
        raise OSError(5, "Input/output error")

    monkeypatch.setattr(Path, "replace", explode)
    with pytest.raises(ConfigurationError):
        save(paths, original)

    leftovers = [p.name for p in paths.root.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == [], "a stale .tmp would be mistaken for state on the next look"


def test_the_temporary_file_shares_the_targets_directory(paths: DataPaths) -> None:
    """`os.replace` is only atomic within one filesystem, and a temp directory may be on another."""
    written: list[Path] = []
    original_replace = Path.replace

    def record(self: Path, target: object) -> Path:
        written.append(self)
        return original_replace(self, target)  # type: ignore[arg-type]

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(Path, "replace", record)
        save(paths, load_or_create(paths))

    assert written, "save() must go through an atomic rename"
    assert written[0].parent == paths.state_file.parent


# --------------------------------------------------------------------------------------------
# Forward compatibility
# --------------------------------------------------------------------------------------------


def test_unknown_keys_survive_a_downgrade(paths: DataPaths) -> None:
    """A newer Atrium writes a key this version does not know; a downgrade must hand it back.

    Dropping it is a data-loss bug that only surfaces after someone has already downgraded to
    escape a different problem - which is the worst possible moment to lose something.
    """
    load_or_create(paths)
    raw = json.loads(paths.state_file.read_text(encoding="utf-8"))
    raw["something_from_the_future"] = {"kept": True}
    paths.state_file.write_text(json.dumps(raw), encoding="utf-8")

    save(paths, load_or_create(paths))

    written = json.loads(paths.state_file.read_text(encoding="utf-8"))
    assert written["something_from_the_future"] == {"kept": True}


def test_a_naive_created_is_read_as_utc(paths: DataPaths) -> None:
    state = ServerState.model_validate(
        {"server_id": "0" * 32, "created": "2026-01-01T00:00:00", "startup_wizard_completed": True}
    )
    assert state.created == datetime(2026, 1, 1, tzinfo=UTC)
