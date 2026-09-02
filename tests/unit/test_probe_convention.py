# SPDX-License-Identifier: GPL-3.0-or-later
"""The prior-measurement register says what is owed, and this asserts it is still true.

`docs/compatibility/reference-target.md` carries the register of prior measurements — claims made
against a real Jellyfin before this repository existed, each a standing debt until a script under
`tools/` reproduces it. 010's AC-9 is *"every prior-measurement debt has a probe script, or a
recorded reason it cannot have one"*, so the register is an **input** to that criterion and not a
narration of it.

Prose cannot be an input. On 2026-09-02 the register said *"six down, nine to go"* over a table
holding seven struck rows and eight open ones, three of the eight named a script nobody had ever
written while the question was already answered by a probe written under another name, and one
named a script that answers half of its claim. Every one of those is invisible to a reader and to a
run: a row saying *"not written"* about work somebody has done makes the debt look bigger than it
is, and a row naming `tools/probe_item_ids.py` makes it look smaller, because the name reads like a
plan.

So three properties are asserted rather than maintained by hand:

* a **struck** row names a script that exists — revert a reconciliation and the name goes back to
  one that is not there;
* an **open** row names a script that exists or writes down why it is still open — a bare
  *"not written"* is neither a probe nor a reason, which is exactly what AC-9 refuses;
* the sentence that counts the table is recomputed **from the table**, so a row added without
  moving it fails here rather than three features later.

The fourth is the 2026-08-28 audit's M8 finding turned into a test: three claims were carrying a
`prior-probe` citation with no register row at all, which is a debt nobody could see. A citation
date that appears in no row of the register is that failure again.

The probe-convention half below is 010 T13's, and it exists for the same reason: **the convention
was a paragraph that nothing read.** Spec §3.5 states four properties of every probe — a shared
entry point, a document and a section it bears on, a non-zero exit on a contradiction, and *"a
probe that writes creates what it needs and removes it, including on failure"*. The last of those
was checked against a real server on 2026-09-01 and did not hold: 009's runs had left **28
playlists** behind, under the names those probes create them with, while `tools/README.md` said
every writing probe deletes what it made. The other three held on all 53 probes and nothing would
have noticed the 54th that did not.

So the four are asserted, and the cleanup one is asserted the way this repository asserts a guard:
`tools/_probe.py`'s shared register is driven with a run that raises, and the test fails if the
`finally` that tears it down is deleted. Two failure modes measured on 2026-09-02 (010 T12) are
asserted **not** to be reported as leaks — a `401` from a revoked token and a connection refused
from an instance that died — because an enforcement that cries wolf is one nobody reads.

No server and no socket: the sweeps are `ast` over files, and the register is driven against a
fake whose only job is to record what was asked of it.
"""

from __future__ import annotations

import ast
import contextlib
import importlib.util
import re
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
REGISTER = ROOT / "docs" / "compatibility" / "reference-target.md"
TOOLS = ROOT / "tools"

#: The register lives under this heading. It is located by heading and not by section number: the
#: table sits inside §2, and 010's task list cited it as §3 — which is the levels table.
HEADING = "### Prior measurements, and the debt they carry"

#: `| a | b | c | d |` — a table row that is neither the header nor the `|---|` separator.
SEPARATOR = re.compile(r"^\|[\s:|-]+\|$")

#: Any script the row names, in the form the documents use everywhere: `tools/probe_x.py`.
SCRIPT = re.compile(r"`(tools/[A-Za-z0-9_]+\.py)`")

#: `**Ten down, five to go**`, in words or digits.
COUNT = re.compile(r"\*\*([A-Za-z]+|\d+) down, ([A-Za-z]+|\d+) to go\*\*")

#: A prior-probe citation anywhere in the documents, with the date it carries.
CITATION = re.compile(r"\[prior-probe:[^\]]*?(\d{4}-\d{2}-\d{2})[^\]]*\]")

#: Directories whose Markdown is not this repository's: other sessions' worktrees, the git-ignored
#: reference material, the virtual environment.
NOT_OURS = {".git", ".claude", "reference", "node_modules", ".venv", "htmlcov"}

#: The register counts itself in words, as the rest of these documents do. Twenty is further than
#: this table has any business growing; past it, write the digits.
SPELLED = (
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
    "sixteen seventeen eighteen nineteen twenty"
)
WORDS = {word: value for value, word in enumerate(SPELLED.split(" "))}

#: What a status cell says when nobody has written a reason. Longer than any of these and carrying
#: something other than a placeholder is the whole test: this is a prose check, and it can only ask
#: that prose exists.
PLACEHOLDERS = {"", "-", "—", "not written", "tbd", "todo", "unknown", "open"}

#: A reason shorter than this is a shrug with punctuation.
REASON = 60


class Row:
    """One register row: its cells, whether it is struck, and the scripts it names."""

    def __init__(self, line: str) -> None:
        self.line = line
        self.cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        self.claim = self.cells[0]
        self.status = self.cells[-1]
        self.struck = self.claim.startswith("~~")
        self.scripts = SCRIPT.findall(line)

    @property
    def name(self) -> str:
        """A pytest id: the claim, without its strike marks, short enough to read in a report."""
        return re.sub(r"[`~*\[\]]", "", self.claim)[:60].strip()


def register_lines() -> list[str]:
    text = REGISTER.read_text(encoding="utf-8")
    start = text.index(HEADING)
    end = text.index("\n### ", start + len(HEADING))
    return text[start:end].splitlines()


def rows() -> list[Row]:
    found: list[Row] = []
    for line in register_lines():
        if not line.startswith("|") or SEPARATOR.match(line) or line.startswith("| Claim "):
            continue
        found.append(Row(line))
    return found


def markdown_files() -> list[Path]:
    return sorted(p for p in ROOT.rglob("*.md") if not set(p.parts) & NOT_OURS)


def number(word: str) -> int:
    return int(word) if word.isdigit() else WORDS[word.lower()]


def test_the_register_was_found_and_has_rows() -> None:
    """A moved heading would otherwise make every test below pass by iterating over nothing."""
    assert len(rows()) > 10, (
        f"{HEADING!r} in {REGISTER.relative_to(ROOT)} holds {len(rows())} table rows. Either the "
        f"heading moved or the table did, and every assertion below has stopped asking anything."
    )


@pytest.mark.parametrize("row", rows(), ids=lambda row: row.name)
def test_every_register_row_names_a_script_that_exists_or_says_why_not(row: Row) -> None:
    missing = [script for script in row.scripts if not (ROOT / script).exists()]

    if row.struck:
        assert row.scripts and not missing, (
            f"the register strikes {row.name!r} but names {missing or 'no script at all'}. A "
            f"struck row is a discharged debt, and a debt is discharged by a script somebody ran "
            f"— so the row names the script that actually answered it, under whatever name that "
            f"script was written. Three rows read 'not written' until 2026-09-02 while the "
            f"question was already answered by a probe belonging to another feature."
        )
        return

    if row.scripts and not missing:
        return

    reason = row.status.strip()
    assert reason.lower().strip("*. ") not in PLACEHOLDERS and len(reason) >= REASON, (
        f"the register leaves {row.name!r} open, names {missing or 'no script'}, and its last "
        f"cell says {reason!r}. 010's AC-9 asks for a probe script *or a recorded reason there "
        f"cannot be one*: a bare 'not written' is neither. Say what is blocking it — an author, a "
        f"configuration this project may not write to an operator's server, or a library it may "
        f"not scan."
    )


def test_the_prose_count_matches_the_table() -> None:
    struck = [row for row in rows() if row.struck]
    open_rows = [row for row in rows() if not row.struck]

    text = "\n".join(register_lines())
    found = COUNT.search(text)
    assert found, (
        f"{REGISTER.relative_to(ROOT)} no longer counts its own register. The sentence reads "
        f"'**N down, M to go**' and this test recomputes it from the rows, because the count was "
        f"wrong in both halves on 2026-09-02 and nothing could see it."
    )

    assert (number(found.group(1)), number(found.group(2))) == (len(struck), len(open_rows)), (
        f"the register says {found.group(0)!r} over a table of {len(struck)} struck rows and "
        f"{len(open_rows)} open ones. The sentence is a summary of the table, so the table wins: "
        f"move the sentence."
    )


def test_every_prior_probe_citation_belongs_to_a_row_of_the_register() -> None:
    """The 2026-08-28 audit's M8: three claims cited a prior measurement no row recorded."""
    registered = {row.cells[1] for row in rows()}
    cited: dict[str, set[str]] = {}
    for path in markdown_files():
        for match in CITATION.finditer(path.read_text(encoding="utf-8")):
            cited.setdefault(match.group(1), set()).add(str(path.relative_to(ROOT)))

    orphans = {date: sorted(where) for date, where in cited.items() if date not in registered}
    assert not orphans, (
        f"prior-probe citations dated {sorted(orphans)} appear in the documents and in no row of "
        f"the register: {orphans}. A debt with no row is a debt nobody is counting — which is what "
        f"the 2026-08-28 audit found three of. Add the row, with the claim and the script that "
        f"would discharge it."
    )


# ------------------------------------------------------------------------------------------
# The probe convention — 010 spec §3.5, AC-7, AC-8 (T13)
# ------------------------------------------------------------------------------------------

#: The methods that reach a write route. `PATCH` is here because a probe that grew one would
#: otherwise be swept past in silence, not because anything sends one today.
WRITING_METHODS = ("POST", "PUT", "PATCH", "DELETE")

#: Calls that use a writing method and change nothing, each with the reason it changes nothing.
#: Two of them, named as `(method, route)` pairs rather than by route: what makes a call harmless
#: here is the pair, and exempting a route wholesale would exempt the `POST` that creates on it.
READ_SHAPED_WRITES = {
    ("POST", "/Items/{}/PlaybackInfo"): "the negotiation - a read whose request carries a body",
    ("PUT", "/UserFavoriteItems/{}"): (
        "a method that route does not serve, sent to read its `Allow` header. The answer is 405 "
        "and nothing is written; behaviours section 1.11 is what it measures"
    ),
}

#: Spellings that parse on 3.9 and **fail at run time** on it. The 3.9 floor is 010 plan D-2 and
#: `tools/README.md` promises it; CI compiles every tool on 3.9 and runs its `--help`, which
#: catches a 3.10 *syntax* and cannot catch these — `zip(..., strict=False)` compiles fine and
#: raises `TypeError: zip() takes no keyword arguments` the moment the line is reached.
#:
#: One shipped: `tools/probe_sidecar_subtitles.py` carried a `zip(..., strict=False)` from 011
#: until 010 T4 read it and T13 removed it. It sat on a path only a real server reaches, which is
#: why nothing found it for two days.
FLOOR_ONLY_ATTRIBUTES = {
    "pairwise": "itertools.pairwise, 3.10",
    "batched": "itertools.batched, 3.12",
    "UTC": "datetime.UTC, 3.11 — the 3.9 spelling is timezone.utc",
}
FLOOR_ONLY_NAMES = {"anext": "anext, 3.10", "aiter": "aiter, 3.10"}
FLOOR_ONLY_MODULES = {"tomllib": "tomllib, 3.11", "graphlib": "graphlib, 3.9 — fine, kept honest"}


def probes() -> list[Path]:
    return sorted(TOOLS.glob("probe_*.py"))


def tools() -> list[Path]:
    return sorted(TOOLS.glob("*.py"))


def tree_of(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"))


def entry_point_calls(tree: ast.AST) -> list[ast.Call]:
    """Every call in this module that reaches `_probe.main`, in the three spellings it has.

    `main(...)` after `from _probe import main`; `_probe.main(...)`; and `load("_probe").main(...)`,
    which is what a probe uses when it also loads `_reference` by path. A fourth spelling is a
    probe that prints its own output, and that is the thing being refused.
    """
    found: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        if isinstance(function, ast.Name) and function.id == "main":
            found.append(node)
        elif isinstance(function, ast.Attribute) and function.attr == "main":
            value = function.value
            by_name = isinstance(value, ast.Name) and value.id == "_probe"
            by_path = (
                isinstance(value, ast.Call)
                and value.args
                and isinstance(value.args[0], ast.Constant)
                and value.args[0].value == "_probe"
            )
            if by_name or by_path:
                found.append(node)
    return found


def imports_the_entry_point(tree: ast.AST) -> bool:
    return any(
        isinstance(node, ast.ImportFrom)
        and node.module == "_probe"
        and any(alias.name == "main" for alias in node.names)
        for node in ast.walk(tree)
    )


def constructs_a_probe(tree: ast.AST) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id == "Probe")
            or (isinstance(node.func, ast.Attribute) and node.func.attr == "Probe")
        )
    ]


def _path_of(argument: ast.AST) -> str:
    """The route a call names, with every interpolation collapsed to `{}`.

    An f-string is how a probe writes `/Items/{item_id}`; what matters is which route it is, not
    which identifier went into it. A path built some other way answers `<computed>`, which counts
    as a write: a call whose route cannot be read is not a call that can be shown to be a read.
    """
    if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
        return argument.value
    if isinstance(argument, ast.JoinedStr):
        return "".join(
            part.value if isinstance(part, ast.Constant) else "{}" for part in argument.values
        )
    return "<computed>"


def write_routes(tree: ast.AST) -> list[str]:
    """Every `(method, route)` this module reaches with a writing method, read off the call.

    Both spellings: the `Server` helpers (`post`, `post_raw`, `delete`, `delete_raw`) and the
    `_request(method, path, ...)` underneath them, which five probes use directly for the
    questions the helpers cannot ask - including the one that sends a `PUT` at a route serving
    `POST` and `DELETE`, to read what its `405` says in `Allow`.
    """
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        name = node.func.attr
        if name in ("post", "post_raw", "delete", "delete_raw"):
            method = "DELETE" if name.startswith("delete") else "POST"
            route = _path_of(node.args[0]) if node.args else "<computed>"
        elif name == "_request" and len(node.args) >= 2:
            method = _path_of(node.args[0])
            if method not in WRITING_METHODS:
                continue
            route = _path_of(node.args[1])
        else:
            continue
        if (method, route) not in READ_SHAPED_WRITES:
            found.append(f"{method} {route}")
    return sorted(set(found))


def declares_writes(tree: ast.AST) -> bool:
    """`needs_writes=True` at the shared entry point: the run refuses without `--allow-writes`."""
    for call in entry_point_calls(tree):
        for keyword in call.keywords:
            if keyword.arg == "needs_writes" and getattr(keyword.value, "value", False) is True:
                return True
    return False


def gates_its_own_writes(tree: ast.AST) -> bool:
    """The second shape, and it is a shape and not a loophole.

    Two probes answer their question **partly** without writing: `probe_playback_info.py` and
    `probe_subtitle_negotiation.py` each carry a battery that needs an account and report the rest
    without one. `needs_writes=True` would refuse the whole run rather than skip that battery, so
    they declare `--allow-writes` themselves and branch on it before writing. The operator says the
    same words either way, which is what the declaration is for.

    Both halves are required. The option alone is a flag nothing reads; the branch alone is a
    branch on an attribute the parser never defines.
    """
    declares = any(
        isinstance(node, ast.Constant) and node.value == "--allow-writes" for node in ast.walk(tree)
    )
    branches = any(
        isinstance(node, ast.Attribute) and node.attr == "allow_writes" for node in ast.walk(tree)
    )
    return declares and branches


def load_probe_module() -> Any:
    """`tools/` is a directory of standalone programs, not an importable package.

    Loaded by path, the way `tests/unit/test_allowlist.py` loads the allowlist reader, and
    registered under its own name because that is the name every probe imports it by.
    """
    if "_probe" in sys.modules:
        return sys.modules["_probe"]
    spec = importlib.util.spec_from_file_location("_probe", TOOLS / "_probe.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["_probe"] = module
    spec.loader.exec_module(module)
    return module


def test_there_are_probes_to_sweep() -> None:
    """A path typo would otherwise make every sweep below pass by iterating over nothing."""
    assert len(probes()) > 40, (
        f"{TOOLS.relative_to(ROOT)} holds {len(probes())} probe_*.py files. The convention sweeps "
        f"below are parametrised over them, so a wrong directory is a green run that asked nothing."
    )


@pytest.mark.parametrize("probe", probes(), ids=lambda path: path.name)
def test_every_probe_reaches_the_shared_entry_point(probe: Path) -> None:
    """AC-7 and AC-8 are properties of `_probe.main`, so they hold only for probes that reach it.

    The citation, the contradiction and the exit code all live in `Probe.report`, which `main` is
    the only caller of. A probe that printed its own output would satisfy the eye and none of the
    criteria — which is exactly the 54th probe this sweep exists to fail.
    """
    tree = tree_of(probe)
    calls = entry_point_calls(tree)
    assert calls, (
        f"tools/{probe.name} never calls `_probe.main`. Spec §3.5's convention is that entry "
        f"point: it parses, connects, runs, reports and translates errors, and AC-7's non-zero "
        f"exit on a contradiction is `Probe.report`'s return value travelling through it. A probe "
        f"that prints its own finding has an output that looks the same and a contract that is not."
    )
    assert imports_the_entry_point(tree) or any(
        isinstance(call.func, ast.Attribute) for call in calls
    ), f"tools/{probe.name} calls something named `main` that does not come from `_probe`"


@pytest.mark.parametrize("probe", probes(), ids=lambda path: path.name)
def test_every_probe_names_a_document_and_a_section(probe: Path) -> None:
    """AC-8: a contradiction produces a message naming the document and section to update.

    `Probe.report` prints both, so the criterion is satisfied exactly when the construction
    supplies both — and a probe that named neither would print a contradiction nobody can act on.
    """
    constructions = constructs_a_probe(tree_of(probe))
    assert constructions, f"tools/{probe.name} constructs no `Probe`, so it reports no finding"
    complete = [
        call
        for call in constructions
        if {"document", "section"} <= {keyword.arg for keyword in call.keywords}
        or len(call.args) >= 4
    ]
    assert complete, (
        f"tools/{probe.name} builds a `Probe` without naming both the document and the section it "
        f"bears on. AC-8 asks a contradiction to name what to update; a finding with no address "
        f"is a finding somebody has to go looking for."
    )


@pytest.mark.parametrize("probe", probes(), ids=lambda path: path.name)
def test_a_probe_that_writes_declares_it(probe: Path) -> None:
    """`needs_writes=True` is what puts `--allow-writes` in front of a write, and it is opt-in.

    The rule is one-directional on purpose. A probe that reaches a write route must declare it; a
    probe that declares it need not post anything — `probe_universal_audio.py` starts an encoder
    with a `GET`, which is a write the server performs and no request body shows.

    It caught two on 2026-09-02, and the first fix for them was wrong.
    `probe_playback_info.py` and `probe_subtitle_negotiation.py` create a user account with
    `POST /Users/New` and pass no `needs_writes`; they turned out to declare `--allow-writes`
    themselves, because for them the flag **adds a battery** rather than gating the run. Passing
    `needs_writes=True` as well made argparse refuse the duplicate option, which CI's own
    `--help` sweep caught. Hence two shapes, and `gates_its_own_writes` is the second.
    """
    tree = tree_of(probe)
    routes = write_routes(tree)
    if not routes:
        return
    assert declares_writes(tree) or gates_its_own_writes(tree), (
        f"tools/{probe.name} reaches {routes} and neither passes `needs_writes=True` to "
        f"`_probe.main` nor declares `--allow-writes` and branches on it itself. Spec §3.5: a "
        f"probe that writes creates what it needs and removes it, and the declaration is what "
        f"makes the operator say `--allow-writes` before it touches their server. The only calls "
        f"exempt are {sorted(READ_SHAPED_WRITES)}, each with the reason it changes nothing "
        f"written down beside it."
    )


@pytest.mark.parametrize("tool", tools(), ids=lambda path: path.name)
def test_no_tool_reaches_for_a_spelling_the_floor_does_not_have(tool: Path) -> None:
    """`tools/` runs on Python 3.9 (010 plan D-2), and CI cannot see this class of breach.

    The `tools` job compiles every file on 3.9 and runs its `--help`, which catches a 3.10 syntax
    and passes a 3.10 *keyword argument* straight through: `zip(a, b, strict=False)` compiles and
    raises `TypeError` when the line runs. One shipped and sat on a server-only path for two days.
    """
    tree = tree_of(tool)
    reached: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "zip":
            reached += [
                "zip(strict=…), 3.10" for keyword in node.keywords if keyword.arg == "strict"
            ]
        elif isinstance(node, ast.Attribute) and node.attr in FLOOR_ONLY_ATTRIBUTES:
            reached.append(FLOOR_ONLY_ATTRIBUTES[node.attr])
        elif isinstance(node, ast.Name) and node.id in FLOOR_ONLY_NAMES:
            reached.append(FLOOR_ONLY_NAMES[node.id])
        elif isinstance(node, ast.Import):
            reached += [
                FLOOR_ONLY_MODULES[alias.name.split(".")[0]]
                for alias in node.names
                if alias.name.split(".")[0] in FLOOR_ONLY_MODULES
            ]
    assert not sorted(set(reached)), (
        f"tools/{tool.name} reaches {sorted(set(reached))}, which the 3.9 floor does not have. "
        f"`tools/README.md` promises a probe runs on the interpreter a machine already has, and "
        f"macOS ships 3.9."
    )


# ------------------------------------------------------------------------------------------
# The cleanup contract, driven rather than described
# ------------------------------------------------------------------------------------------


class Recording:
    """A `Server` that records what was asked of it and answers however the test needs.

    Not a `Mock`: the register calls exactly one method on a server, and a fake that can only do
    that is a fake that cannot pass for the wrong reason.
    """

    def __init__(self, base: str = "http://recorded", refuse: Any = None) -> None:
        self.base = base
        self.version = "10.11.11"
        self.deleted: list[str] = []
        self.refuse = refuse

    def delete(self, path: str, **_: Any) -> None:
        self.deleted.append(path)
        if self.refuse is not None:
            raise self.refuse


@contextlib.contextmanager
def a_run(module: Any, argv: tuple[str, ...], monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """`_probe.main` as a test drives it: its own argv, no `.env`, and an empty register.

    `load_env_file` is stubbed rather than allowed to run, because it reads the repository's
    git-ignored `.env` into `os.environ` and a test has no business putting an operator's
    credentials into the process it runs in.
    """
    monkeypatch.setattr(sys, "argv", list(argv))
    monkeypatch.setattr(module, "load_env_file", lambda *args, **kwargs: None)
    module.OWNED.clear()
    try:
        yield
    finally:
        module.OWNED.clear()


def test_report_returns_one_on_a_contradiction(capsys: pytest.CaptureFixture[str]) -> None:
    """AC-7, driven through `Probe.report` rather than asserted about it."""
    module = load_probe_module()
    probe = module.Probe(
        script="probe_example.py",
        question="does the documented thing happen?",
        document="docs/compatibility/behaviours.md",
        section="§9.9",
        expectation="it happens",
    )
    probe.conclude("it does not happen", matches_documentation=False)
    assert probe.report(Recording()) == 1
    probe.conclude("it happens", matches_documentation=True)
    assert probe.report(Recording()) == 0, (
        "a probe whose finding agrees with the documentation exits zero, or the non-zero above "
        "proves nothing: a report that always failed would satisfy AC-7 and no run would ever pass"
    )
    capsys.readouterr()


def test_a_contradiction_names_the_document_and_the_section(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC-8: the message says what to go and update, not merely that something is wrong."""
    module = load_probe_module()
    probe = module.Probe(
        script="probe_example.py",
        question="does the documented thing happen?",
        document="docs/compatibility/behaviours.md",
        section="§9.9",
        expectation="it happens",
    )
    probe.conclude("it does not happen", matches_documentation=False)
    assert probe.report(Recording()) == 1
    printed = capsys.readouterr().out
    assert "CONTRADICTION" in printed
    assert "docs/compatibility/behaviours.md" in printed and "§9.9" in printed, (
        "a contradiction that names neither the document nor the section leaves the reader to "
        "find out which of thirty compatibility sections just became false"
    )


def test_a_writing_probe_that_leaks_fails_the_sweep(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The requirement the server disproved on 2026-09-01, turned into a test.

    A probe registers something it created and then **raises**. The teardown is a `finally` inside
    `main`, so the object is removed anyway. Delete that `finally` and this fails, which is this
    repository's standard for a guard.
    """
    module = load_probe_module()
    server = Recording()

    @contextlib.contextmanager
    def connect_with(_args: Any) -> Iterator[Any]:
        yield server

    def run(connected: Any, _args: Any) -> Any:
        module.OWNED.own(connected, "/Items/abcdef", "playlist")
        raise module.ProbeError("the question could not be answered")

    with a_run(module, ("probe_example.py", "--allow-writes"), monkeypatch):
        code = module.main(
            run, "example", needs_writes=True, with_args=True, connect_with=connect_with
        )

    assert server.deleted == ["/Items/abcdef"], (
        "the run created a playlist and then failed, and the playlist is still on the server. "
        "Spec §3.5: a probe that writes removes what it made **including on failure** — which is "
        "the sentence 009's runs falsified 28 times over. The teardown belongs in a `finally`."
    )
    assert code == 2, "an unanswerable question is exit 2, and a cleanup does not change that"
    capsys.readouterr()


def test_a_leak_the_register_could_not_remove_fails_the_run(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A probe with a defect exits non-zero, and with its own code rather than a finding's."""
    module = load_probe_module()
    server = Recording(refuse=module.ProbeError("DELETE /Items/x -> HTTP 500", status=500))

    @contextlib.contextmanager
    def connect_with(_args: Any) -> Iterator[Any]:
        yield server

    def run(connected: Any, _args: Any) -> Any:
        module.OWNED.own(connected, "/Items/abcdef", "playlist")
        probe = module.Probe("probe_example.py", "q", "doc.md", "§1", expectation="so")
        probe.conclude("so", matches_documentation=True)
        return probe

    with a_run(module, ("probe_example.py", "--allow-writes"), monkeypatch):
        code = module.main(
            run, "example", needs_writes=True, with_args=True, connect_with=connect_with
        )

    assert code == module.CLEANUP_FAILED
    assert "still on the server" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("failure", "reason"),
    [
        ({"status": 401}, "REVOKED"),
        ({"transport": True}, "UNREACHABLE"),
        ({"status": 404}, "ALREADY_GONE"),
    ],
    ids=["a revoked token", "a server that stopped answering", "something already gone"],
)
def test_the_three_failures_that_are_not_a_leak_are_not_reported_as_one(
    failure: Any, reason: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """010 T12 measured two of these against a real pair of servers, and neither is a leak.

    The reference binds a token to a device, so a second sign-in revokes the first token and every
    `DELETE` after it answers `401`; and the single-use instance dies with `SIGILL` often enough to
    have been counted — four of eight starts on 2026-09-02 — after which nothing answers at all.
    Reporting either as *"the probe forgot to clean up"* is how an enforcement stops being read.
    """
    module = load_probe_module()
    server = Recording(refuse=module.ProbeError("DELETE /Items/x -> refused", **failure))

    @contextlib.contextmanager
    def connect_with(_args: Any) -> Iterator[Any]:
        yield server

    def run(connected: Any, _args: Any) -> Any:
        module.OWNED.own(connected, "/Items/abcdef", "playlist")
        probe = module.Probe("probe_example.py", "q", "doc.md", "§1", expectation="so")
        probe.conclude("so", matches_documentation=True)
        return probe

    with a_run(module, ("probe_example.py", "--allow-writes"), monkeypatch):
        code = module.main(
            run, "example", needs_writes=True, with_args=True, connect_with=connect_with
        )

    assert code == 0, (
        f"{reason} was reported as a leak and failed the run. It is not one: the object is either "
        f"already gone, or unreachable, or behind a token somebody else revoked, and a harness "
        f"that cries wolf on all three is one nobody reads by the second week (spec §6)."
    )
    printed = capsys.readouterr().err
    assert getattr(module, reason) in printed
    assert "nothing explains it" not in printed


def test_a_probe_that_removes_its_own_creation_leaves_nothing_to_tear_down() -> None:
    """The two mechanisms must not fight: a probe's own `finally` de-registers what it removed.

    Twenty-six probes have a teardown of their own, and the register is not allowed to issue a
    second `DELETE` behind them — a double delete answers `404` and would report a leak on the
    probes that are doing exactly what §3.5 asks.
    """
    module = load_probe_module()
    module.OWNED.clear()
    server = Recording()
    module.OWNED.note(server, "POST", "/Playlists", {"Id": "abcdef"})
    assert len(module.OWNED) == 1
    module.OWNED.note(server, "DELETE", "/Items/abcdef", None)
    assert len(module.OWNED) == 0
    assert module.OWNED.teardown() == []
    assert server.deleted == []
    module.OWNED.clear()


def test_a_creation_is_registered_without_the_probe_being_changed() -> None:
    """Why the register is in `Server` and not in twenty-eight scripts.

    The 28 playlists were left by probes that each had a teardown; what none of them had was a
    teardown that ran when the path out was not the one it was written for. Recording the creation
    where the creation happens is what makes the contract hold for the probes nobody has edited.
    """
    module = load_probe_module()
    module.OWNED.clear()
    server = Recording()
    module.OWNED.note(server, "POST", "/Playlists", b'{"Id":"abc123"}')
    module.OWNED.note(server, "POST", "/Users/New", {"Id": "def456", "Name": "throwaway"})
    module.OWNED.note(server, "POST", "/Playlists", {"ErrorCode": "no Id here"})
    assert len(module.OWNED) == 2, (
        "a refused creation registers nothing: a `POST /Playlists` that answered no identifier "
        "created no playlist, and a teardown chasing one would report a leak on every probe that "
        "measures a refusal"
    )
    assert module.OWNED.teardown() == []
    assert server.deleted == ["/Users/def456", "/Items/abc123"], (
        "the teardown removes newest first: a run creates a seat and then writes as it, so "
        "deleting the account first takes the token the rest of the cleanup needs"
    )
    module.OWNED.clear()


def test_no_tool_writes_the_device_id_out_by_hand() -> None:
    """Every device a request names is **this connection's**, and one place decides what that is.

    The base was a module constant and five files had copied its value into a string literal: a
    `stop_encoding`, a `DELETE /Videos/ActiveEncodings`, a session lookup, a `/universal` query and
    a progressive-production query. Deriving a device per account (above) made every one of those
    name a device nothing was signed in from — silently, since a stop that names the wrong device
    stops nothing and a session lookup that finds nothing looks like a session that ended.

    So the literal appears in `_probe.py` and nowhere else. A sixth copy fails here rather than by
    leaving an encoder running on somebody's server.
    """
    module = load_probe_module()
    offenders = {
        tool.name: module.DEVICE_ID
        for tool in tools()
        if tool.name != "_probe.py" and module.DEVICE_ID in tool.read_text(encoding="utf-8")
    }
    assert not offenders, (
        f"{sorted(offenders)} write {module.DEVICE_ID!r} out as a literal. It is the **base** of a "
        f"device id and not one: `_probe.Server.device_id` is what a request names, and a copy of "
        f"the base names a device no account signed in from."
    )


def test_two_accounts_do_not_share_one_device() -> None:
    """010 T12's finding, as a property of `_probe.Server` rather than of one probe's workaround.

    Two accounts under one `DeviceId` are one session on the reference, and the second sign-in
    revokes the first's token — which is a live hazard for a shared teardown, since the token being
    revoked is the administrator's and the cleanup is the administrator's to do.
    `probe_session_filters.py` used to swap a module constant around its second sign-in; it was the
    only probe that did, and every other one that signs in twice was exposed.
    """
    module = load_probe_module()
    assert module.device_for("administrator") != module.device_for("throwaway")
    assert module.device_for("administrator") == module.device_for("administrator")
    assert module.device_for("administrator").startswith(module.DEVICE_ID)
