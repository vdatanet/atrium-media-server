# SPDX-License-Identifier: GPL-3.0-or-later
"""The hook that refuses a commit on `main`, exercised as git runs it.

**AGENTS.md has carried "never commit to `main`" since 001, and it has been broken twice** — once
before 2026-09-06 and once on it. Both times what caught it was luck of the same kind: a push or a
pull-request creation failing afterwards, with a message about something else. Nothing in the
repository refused the commit itself, so the rule was a sentence rather than a gate.

This tests the hook the way git uses it — a real repository, a real `git commit`, the repository's
own `.githooks` as `core.hooksPath` — because a hook asserted by reading its text is a hook that
has never been run. It is also why the test builds its own repository rather than touching this
one: a test that committed here to see what happens would be the very thing being prevented.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parents[2] / ".githooks"
HOOK = HOOKS / "pre-commit"


def git(
    *arguments: str, cwd: Path, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - git, with arguments this test wrote
        ["git", *arguments],  # noqa: S607 - on PATH, and the suite needs it anyway
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    """A repository of its own, pointed at this project's hooks."""
    root = tmp_path / "clone"
    root.mkdir()
    git("init", "-q", "-b", "main", ".", cwd=root)
    git("config", "user.email", "hook@test", cwd=root)
    git("config", "user.name", "hook test", cwd=root)
    git("config", "core.hooksPath", str(HOOKS), cwd=root)
    return root


def test_the_hook_is_executable() -> None:
    """A hook git cannot execute is a hook git skips, silently and with no error anywhere."""
    assert HOOK.is_file()
    assert HOOK.stat().st_mode & 0o111, "git runs a hook by executing it; this one has no bit set"


def test_a_commit_on_main_is_refused(repository: Path) -> None:
    made = git("commit", "-q", "--allow-empty", "-m", "on main", cwd=repository)

    assert made.returncode != 0
    assert "refusing a commit on main" in made.stderr
    assert git("log", "--oneline", cwd=repository).stdout == "", "the commit was made anyway"


def test_the_refusal_says_how_to_recover(repository: Path) -> None:
    """The message is the whole of the hook's usefulness: somebody meets it mid-task with work in
    the tree, and needs to know that nothing is lost and what to type."""
    made = git("commit", "-q", "--allow-empty", "-m", "on main", cwd=repository)

    assert "git checkout -b" in made.stderr
    assert "git branch" in made.stderr and "git reset --hard origin/main" in made.stderr
    assert "ALLOW_COMMIT_ON_MAIN=1" in made.stderr


def test_a_commit_on_a_branch_is_allowed(repository: Path) -> None:
    git("checkout", "-q", "-b", "fix/something", cwd=repository)

    made = git("commit", "-q", "--allow-empty", "-m", "on a branch", cwd=repository)

    assert made.returncode == 0, made.stderr
    assert "on a branch" in git("log", "--oneline", cwd=repository).stdout


def test_the_escape_hatch_works(repository: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Repairing `main` itself is the one case that is not a mistake, and it has to stay possible
    without editing the hook — which is what somebody would otherwise do, permanently."""
    import os

    env = dict(os.environ, ALLOW_COMMIT_ON_MAIN="1")
    made = git("commit", "-q", "--allow-empty", "-m", "deliberate", cwd=repository, env=env)

    assert made.returncode == 0, made.stderr
    assert "deliberate" in git("log", "--oneline", cwd=repository).stdout


def test_a_detached_head_is_not_main(repository: Path) -> None:
    """A rebase and a bisect both leave `HEAD` detached, and neither is a commit on `main`.

    `git symbolic-ref` fails there rather than answering, which the hook reads as "not main" — the
    direction that matters, because a hook that refused during a rebase would be turned off.
    """
    git("checkout", "-q", "-b", "work", cwd=repository)
    git("commit", "-q", "--allow-empty", "-m", "first", cwd=repository)
    head = git("rev-parse", "HEAD", cwd=repository).stdout.strip()
    git("checkout", "-q", head, cwd=repository)

    made = git("commit", "-q", "--allow-empty", "-m", "detached", cwd=repository)

    assert made.returncode == 0, made.stderr
