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
# `api/` owns no SQL
# ------------------------------------------------------------------------------------------

#: 005 plan section 9 row 2: "an endpoint bypasses the shared pipeline and drifts", whose impact
#: is High because the visibility predicate is the security-relevant piece of the feature. The
#: mitigation is that route modules own no SQL - one repository is the only reader, so seventeen
#: endpoints inherit the predicate instead of each remembering it.
#:
#: Load-bearing from T10 on, when `api/` has eleven modules and every one of them is a list
#: endpoint. Asserted now rather than then, because the first route to reach for a session is the
#: one that gets away with it.
NO_SQL_ABOVE = ("sqlalchemy",)

#: **`deps.py` is the exception, and it was already one when 005 T5 said there were none.** It is
#: the dependency-wiring module rather than a route: it hands routes the session factory, which is
#: precisely the boundary object the rule exists to route everything through. A rule that excluded
#: it would have to be satisfied by moving the wiring somewhere `api/` imports anyway, which is
#: the same code in a worse place.
#:
#: The exemption is narrow on purpose. `deps.py` may **name** the session types; the moment it
#: imports something that builds a statement it is writing queries in the routing layer, which is
#: the thing being forbidden.
WIRING = "deps.py"
WIRING_MAY_IMPORT = frozenset({"Session", "sessionmaker", "OrmSession"})

#: `atrium.db.models` by name rather than `atrium.db` wholesale: a route legitimately holds a
#: **repository**, which is the boundary object. What it may not hold is a row.
NO_ROWS_ABOVE = ("atrium.db.models",)


def api_modules() -> list[Path]:
    return sorted((PACKAGE / "api").rglob("*.py"))


def test_there_are_api_modules_to_check() -> None:
    assert api_modules(), f"no modules found under {PACKAGE / 'api'}"


@pytest.mark.parametrize("module", api_modules(), ids=lambda path: path.name)
def test_a_route_module_writes_no_sql(module: Path) -> None:
    """The rule is about *reaching for* SQL, so it names the toolkit rather than a pattern: a
    module that imports `sqlalchemy` at all has a session or a statement in it somewhere."""
    tree = ast.parse(module.read_text(encoding="utf-8"))
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
    if module.name == WIRING:
        pytest.skip(
            f"{WIRING} is the wiring module; test_the_wiring_module_only_names_types holds it"
        )
    reached = sorted(imported & set(NO_SQL_ABOVE))
    assert not reached, (
        f"atrium/api/{module.name} imports {reached}. Route modules own no SQL: the item "
        f"repository is the only reader, which is what makes the visibility predicate impossible "
        f"for an endpoint to forget (005 plan section 9 row 2). A route holds a repository, not a "
        f"session."
    )


def test_the_wiring_module_only_names_types() -> None:
    """The narrow half of the exemption above.

    `api/deps.py` imports from `sqlalchemy` and always will - it is what hands a route its session
    factory. What it must never import is something that *builds* a statement: `select`, `delete`,
    `update`, `text`. Those would be SQL in the routing layer wearing a dependency's clothes.
    """
    module = PACKAGE / "api" / WIRING
    tree = ast.parse(module.read_text(encoding="utf-8"))
    names = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.level == 0
        and (node.module or "").startswith("sqlalchemy")
        for alias in node.names
    }
    beyond = sorted(names - WIRING_MAY_IMPORT)
    assert not beyond, (
        f"atrium/api/{WIRING} imports {beyond} from sqlalchemy. It may name the session types and "
        f"nothing else: anything that builds a statement is SQL in the routing layer."
    )


@pytest.mark.parametrize("module", api_modules(), ids=lambda path: path.name)
def test_a_route_module_never_holds_a_row(module: Path) -> None:
    """A repository is a boundary object and a route may hold one. A `models.Item` is a row, and a
    route that has one has bypassed the boundary rather than crossed it."""
    tree = ast.parse(module.read_text(encoding="utf-8"))
    reached = sorted(
        {name for node in ast.walk(tree) for name in _dotted_targets(node) if name in NO_ROWS_ABOVE}
    )
    assert not reached, (
        f"atrium/api/{module.name} imports {reached}. The repository returns domain objects, "
        f"never rows - `tests/unit/test_repositories.py` asserts that end of it, and this is the "
        f"other."
    )


def _dotted_targets(node: ast.AST) -> set[str]:
    if isinstance(node, ast.Import):
        return {alias.name for alias in node.names}
    if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
        return {node.module} | {f"{node.module}.{alias.name}" for alias in node.names}
    return set()


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
#: **`byname.py` was here for the fold, and the fold moved.** T4 put it in
#: `library/identity.py`, because the by-name *identity* is derived from it and two definitions of
#: one fold is how a spelling merges into one row and derives another's id. So `byname.py` calls
#: across to `library/` and cannot be in this list - and the guarantee did not evaporate, it
#: followed the code: `PURE_BY_NAME` below holds `library/identity.py` to the no-I/O half of the
#: same rule. Splitting the fold back out to satisfy a tuple would be the tail wagging the dog;
#: deleting the guarantee would be worse.
PURE_METADATA = ("model.py", "merge.py")

#: Modules that are pure in the sense that matters here - **no I/O** - wherever they happen to
#: live. `library/identity.py` derives every identifier in the project from strings, and a version
#: of it that could read a file could derive an identifier from something that changes.
#:
#: `media/decision.py` joined them at 008 T4, and for the same reason at a larger scale: the whole
#: of the playback ladder is one function of four values, which is what lets seven routes inherit
#: one set of semantics and lets those semantics be a table instead of seven negotiations. A
#: version of it that could open the file it is negotiating about would decide from something the
#: negotiation was not handed.
PURE_WHEREVER_THEY_LIVE = (
    "library/identity.py",
    "media/decision.py",
    "metadata/byname.py",
    # 008 T6. `compat/ranges.py` reads a header and a number and answers which bytes to send; a
    # version of it that could open the file would be a version that could answer from the file
    # instead of from the header, and the measured matrix would stop being a table of values.
    # `media/labels.py` beside it is a measured lookup table and nothing else.
    "compat/ranges.py",
    "media/labels.py",
    # 011 T5. `media/subtitles.py` is one half of a deliberate split (011 plan section 3): the
    # cue list is values and `media/extract.py` beside it is the only thing that starts a
    # process. A version of this module that could open the subtitle file would erase the split
    # and take a scratch directory into every cue test.
    "media/subtitles.py",
)

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


@pytest.mark.parametrize("relative", PURE_WHEREVER_THEY_LIVE)
def test_a_module_that_is_pure_by_nature_opens_nothing(relative: str) -> None:
    """The half of the rule that survives a module moving between packages."""
    module = PACKAGE / relative
    assert module.exists(), f"{relative} does not exist"
    _assert_opens_nothing(module, relative)


@pytest.mark.parametrize("module", pure_metadata_modules(), ids=lambda path: path.name)
def test_a_pure_metadata_module_opens_nothing(module: Path) -> None:
    _assert_opens_nothing(module, f"atrium/metadata/{module.name}")


def _assert_opens_nothing(module: Path, described: str) -> None:
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
    assert not reached, f"{described} reaches {reached}, and it is pure"


# ------------------------------------------------------------------------------------------
# Every ffmpeg has an owner
# ------------------------------------------------------------------------------------------

#: architecture.md section 4 says every external process this server starts belongs to something
#: that can stop it, and 008 makes that load-bearing: an encoder nobody owns keeps running after
#: the client that wanted it has gone, and a server that accumulates those dies of them.
#:
#: **Two** modules may reach for a process, and the 008 task list expected three: it named
#: `media/sessions.py` beside these, and the manager turned out not to need the capability at
#: all. It starts everything through the ledger, so the exemption would have been a hole rather
#: than a permission - and the sweep is stronger without it, because a manager that grew its own
#: `create_subprocess_exec` would be a manager whose processes the ledger does not list.
#:
#: `media/probe.py` runs ffprobe to completion and reads its output; `media/ffmpeg.py` holds the
#: `ProductionLedger`, which is the whole set of live processes and the thing AC-26 asks to be
#: empty. A sweep rather than a discipline: the third module to spawn a process fails this test
#: on the line that imports the capability, which is a great deal earlier than the operator
#: noticing.
MAY_START_A_PROCESS = ("media/probe.py", "media/ffmpeg.py")

#: The owner the task list expected to need an exemption. Checked explicitly rather than left to
#: the sweep, because "it happens not to import subprocess today" and "it starts its processes
#: through the ledger on purpose" are the same test result and different facts.
SUPERVISED_THROUGH_THE_LEDGER = "media/sessions.py"


def package_modules() -> list[Path]:
    return sorted(PACKAGE.rglob("*.py"))


@pytest.mark.parametrize("relative", [*MAY_START_A_PROCESS, SUPERVISED_THROUGH_THE_LEDGER])
def test_the_supervised_modules_exist_to_be_checked(relative: str) -> None:
    """A renamed module would otherwise make the sweep below pass by exempting nothing."""
    assert (PACKAGE / relative).exists(), f"{relative} does not exist under atrium/"


def process_spawners(module: Path) -> list[str]:
    """Which of the two spellings that start a process this module reaches for.

    `subprocess` and `asyncio.create_subprocess_*`. Named rather than pattern-matched, because
    what is being detected is *reaching for* the capability: a module that imports either has a
    process in it somewhere.
    """
    tree = ast.parse(module.read_text(encoding="utf-8"))
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        for alias in getattr(node, "names", [])
        if isinstance(node, ast.Import)
    } | {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module
    }
    return sorted(
        {name for name in ("subprocess",) if name in imported}
        | {
            f"asyncio.{node.attr}"
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute) and node.attr.startswith("create_subprocess")
        }
    )


@pytest.mark.parametrize("module", package_modules(), ids=lambda path: path.name)
def test_only_a_supervised_module_starts_a_process(module: Path) -> None:
    relative = module.relative_to(PACKAGE).as_posix()
    if relative in MAY_START_A_PROCESS:
        pytest.skip(f"{relative} is one of the supervised set")
    spawners = process_spawners(module)
    assert not spawners, (
        f"atrium/{relative} reaches {spawners}. Every external process this server starts has an "
        f"owner that can stop it (architecture.md section 4), and the owners are "
        f"{list(MAY_START_A_PROCESS)}: a probe run to completion, and the ledger that holds every "
        f"live production. A session owns its encoder *through* the ledger, which is what keeps "
        f"'every ffmpeg has an owner' one set to sweep rather than two."
    )


def test_the_two_supervised_modules_really_do_start_processes() -> None:
    """Otherwise the exemptions above are two names nothing needs, and the sweep proves nothing."""
    for relative in MAY_START_A_PROCESS:
        assert process_spawners(PACKAGE / relative), (
            f"atrium/{relative} starts no process any more; it should not be exempt from the "
            f"sweep either"
        )


def test_the_transcode_manager_starts_its_encoders_through_the_ledger() -> None:
    """008 T11's own shape, asserted rather than described.

    The manager decides *which* process to start and *when* to kill it; the ledger is what
    actually spawns and reaps. Written down here because the alternative reads identically in a
    diff - a `create_subprocess_exec` inside the manager would work, pass every segment test, and
    quietly make the ledger a partial list of what this server is running.
    """
    module = PACKAGE / SUPERVISED_THROUGH_THE_LEDGER
    assert process_spawners(module) == []
    assert "_ledger.start(" in module.read_text(encoding="utf-8")


# ------------------------------------------------------------------------------------------
# `images/` knows nothing about HTTP, and owns no SQL
# ------------------------------------------------------------------------------------------

#: 006 plan section 3 draws the line twice, in both directions: `api/images.py` owns the wire -
#: headers, `304`, the two error statuses - and `images/` owns bytes. The route rule above already
#: keeps SQL out of `api/`; this keeps the *framework* out of `images/`, which is the half that
#: would rot quietly. A resize that reached for a `Request` to read `Accept` would work, pass its
#: own tests, and make the transform impossible to table-test as values.
#:
#: SQL is here too, and for a different reason: the repository is the only reader (005 plan
#: section 9 row 2). `images/source.py` legitimately imports the repository's **record types** -
#: what it must not do is build a statement.
IMAGES_MAY_NOT_IMPORT = ("fastapi", "starlette", "sqlalchemy", "httpx")


def image_modules() -> list[Path]:
    return sorted((PACKAGE / "images").rglob("*.py"))


def test_there_are_image_modules_to_check() -> None:
    assert image_modules(), f"no modules found under {PACKAGE / 'images'}"


@pytest.mark.parametrize("module", image_modules(), ids=lambda path: path.name)
def test_an_image_module_knows_nothing_about_http_or_sql(module: Path) -> None:
    tree = ast.parse(module.read_text(encoding="utf-8"))
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
    reached = sorted(imported & set(IMAGES_MAY_NOT_IMPORT))
    assert not reached, (
        f"atrium/images/{module.name} imports {reached}. `images/` owns bytes and knows nothing "
        f"about HTTP (006 plan section 3): a header, a status code or a query parameter belongs "
        f"in atrium/api/images.py, and a statement belongs in a repository."
    )
