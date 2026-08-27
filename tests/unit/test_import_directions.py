# SPDX-License-Identifier: GPL-3.0-or-later
"""`domain/` is the bottom of the stack, asserted rather than intended.

architecture.md section 1 draws `domain/` under everything and says it performs no I/O of any
kind. Nothing enforced that: the rule lived in a diagram, and the first `from atrium.db import ...`
inside a domain module would have been an ordinary-looking line in an ordinary-looking pull
request that quietly inverted the dependency the whole shape rests on.

The rule asserted here is the strong form - **a domain module imports the standard library and
other domain modules, and nothing else**. `library/`, `db/` and `api/` are the three the task named
and the three that would hurt most, but `compat/` would be just as wrong: it exists to know that
the wire format is Jellyfin's, and a domain object that knew would make the conformance sweep
unenforceable.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[2] / "src" / "atrium"
DOMAIN = PACKAGE / "domain"

#: Named in the failure message because these are the inversions that matter, not because the
#: others are allowed.
THE_ONES_THAT_HURT = ("library", "db", "api")


def imported_packages(module: Path) -> set[str]:
    """Every `atrium.<package>` this module imports, absolute and relative forms both."""
    tree = ast.parse(module.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("atrium."):
                    found.add(alias.name.split(".")[1])
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                # `from . import x` inside atrium/domain/ means atrium.domain.
                found.add(DOMAIN.name if node.level == 1 else "")
            elif node.module and node.module.startswith("atrium."):
                found.add(node.module.split(".")[1])
    return found - {""}


def domain_modules() -> list[Path]:
    return sorted(DOMAIN.rglob("*.py"))


def test_there_are_domain_modules_to_check() -> None:
    """A path typo would otherwise make every test below pass by iterating over nothing."""
    assert domain_modules(), f"no modules found under {DOMAIN}"


@pytest.mark.parametrize("module", domain_modules(), ids=lambda path: path.name)
def test_a_domain_module_imports_nothing_above_it(module: Path) -> None:
    outside = sorted(imported_packages(module) - {"domain"})
    assert not outside, (
        f"atrium/domain/{module.name} imports atrium.{{{', '.join(outside)}}}. `domain/` is the "
        f"bottom of the stack (architecture.md section 1): everything may depend on it and it "
        f"depends on nothing. {list(THE_ONES_THAT_HURT)} are the inversions that would hurt most "
        f"- a domain object that knows about storage or HTTP takes both of them everywhere it "
        f"goes."
    )


@pytest.mark.parametrize("module", domain_modules(), ids=lambda path: path.name)
def test_a_domain_module_opens_nothing(module: Path) -> None:
    """ "No I/O of any kind" is the other half of the rule, and it is cheap to check for the
    obvious spellings: a domain module that grows a file read or a socket did not mean to.
    """
    source = module.read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden = {"open", "socket", "sqlite3", "requests", "httpx", "urllib", "subprocess", "os"}
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module
    }
    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    reached = sorted((imported | called) & forbidden)
    assert not reached, (
        f"atrium/domain/{module.name} reaches {reached}, and domain/ performs no I/O"
    )


# ------------------------------------------------------------------------------------------
# The pure core of `metadata/`
# ------------------------------------------------------------------------------------------

#: Plan section 3 calls three things in `metadata/` pure - `model.py`, `merge.py` and the fold in
#: `byname.py` - and the whole testing strategy rests on it: the precedence matrix of section 6.1
#: is a table of plain values only for as long as nothing in that path can reach a database, a
#: file or a socket. The rest of `metadata/` is *supposed* to reach outwards; `tags.py` implements
#: 003's seam and `refresh.py` calls the write repository, so this is a list rather than a
#: directory.
#:
#: `byname.py` is here for the fold. If that module ever needs the session it was designed to
#: avoid, the honest change is to split the fold out - not to delete a line from this tuple.
PURE_METADATA = ("model.py", "merge.py", "byname.py")

#: `compat/` belongs here for the same reason it belongs in the domain rule: it exists to know
#: that the wire format is Jellyfin's, and a pure merge that knew would be untestable as values.
ABOVE_THE_PURE_CORE = ("db", "api", "library", "compat", "net", "users")


def pure_metadata_modules() -> list[Path]:
    return [path for name in PURE_METADATA if (path := PACKAGE / "metadata" / name).exists()]


def test_the_pure_metadata_modules_exist_to_be_checked() -> None:
    """Written as `exists()` above because these arrive across T3, T6 and T9. The moment one is
    committed it is checked; until then this test says which are still missing rather than
    passing over an empty list.
    """
    missing = [name for name in PURE_METADATA if not (PACKAGE / "metadata" / name).exists()]
    assert len(missing) < len(PURE_METADATA), (
        f"none of {list(PURE_METADATA)} exists under atrium/metadata - a path typo would make "
        f"every test below pass by iterating over nothing"
    )


@pytest.mark.parametrize("module", pure_metadata_modules(), ids=lambda path: path.name)
def test_a_pure_metadata_module_imports_nothing_that_does_i_o(module: Path) -> None:
    reached = sorted(imported_packages(module) & set(ABOVE_THE_PURE_CORE))
    assert not reached, (
        f"atrium/metadata/{module.name} imports atrium.{{{', '.join(reached)}}}. Plan section 3 "
        f"calls this module pure, and section 8 makes the precedence matrix a table test on the "
        f"strength of it. `domain/` is the one package it may reach."
    )


@pytest.mark.parametrize("module", pure_metadata_modules(), ids=lambda path: path.name)
def test_a_pure_metadata_module_opens_nothing(module: Path) -> None:
    tree = ast.parse(module.read_text(encoding="utf-8"))
    forbidden = {"open", "socket", "sqlite3", "requests", "httpx", "urllib", "subprocess", "os"}
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module
    }
    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    reached = sorted((imported | called) & forbidden)
    assert not reached, f"atrium/metadata/{module.name} reaches {reached}, and it is pure"
