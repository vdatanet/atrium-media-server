#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""The version bump, as four steps in order with no way past a failure.

[conformance.md](../docs/compatibility/conformance.md) defines the procedure and this makes it
executable: fetch the new document and validate the surface, run the differential and the named
comparisons, re-run every probe and re-date the documents they support, and **only then** write
the pin. It is a sequencer, not a new mechanism - every step is a program that already exists -
and the sequence is the product.

**A bump that half-succeeds is worse than one that never ran.** The whole compatibility argument
in this repository rests on a pinned version: a new pin over stale readings is a document that
says a measurement was taken against a server nobody measured. So a step that fails stops the
procedure, every later step is reported NOT RUN rather than skipped quietly, and nothing
downstream ever runs on an input an earlier step did not produce. *"A bump that skips step 2 has
not been done, it has been declared."*

**The two rows of [reference-target section 1](../docs/compatibility/reference-target.md) move
separately, and which move this is is measured rather than declared.** The running reference is
asked its own version, and it is compared with the behavioural row this repository pins today:

* the two agree - the same server, a different document of it - and step 2 has no input. The
  command says so and skips it, which is the move that was actually made on 2026-09-01;
* they differ - the running reference changed - and step 2 is **mandatory**. There is no flag that
  skips it, because the decision reads a measurement and never an argument;
* the version cannot be read at all, and the procedure **stops before step 1**. An unreadable
  version is never "contract-only": guessing that way is the one path that ends in a new pin over
  readings nobody took.

**What distinguishes "the reference changed" from "the container died".** Both arrive as a
non-zero exit from a child, and treating them as one thing produces either a false triage or a
false bump. They are separated by the exit codes the children already promise:

* `0` - the documentation is confirmed, or the differential run is clean.
* `1` - a **contradiction**: the reference disagrees with something this repository claims. From
  `differential.py`, `1` covers two things and its own summary line separates them: a difference
  it found, and a case it never got to ask.
* `2` - it could not look. No connection, no credential, no instance; or the run could not start.
* `3` - a probe created something it could not remove (010 T13).

So a container that dies with `SIGILL` - which the pinned image does often enough to have been
counted, four of eight starts on 2026-09-02 (010 plan section 7) - reaches this command as `2`,
because all three probes that stand up their own instance convert an `InstanceError` into a
`ProbeError` and `_probe.main` answers `2` for that. `COULD_NOT_LOOK` is therefore its own outcome
and never a finding: the procedure stops and says **nothing was measured**, where a `CHANGED` says
a measurement disagreed. `tests/unit/test_version_bump.py` asserts the conversion on every probe
that makes its own instance, because the distinction is only as good as that contract.

**What this command deliberately does not distinguish**: a reference that died mid-run from one
that was never reachable. Both are `COULD_NOT_LOOK`, both mean nothing was measured, and both have
the same remedy - run it again, or stand an instance up by hand with `tools/reference_instance.py`
and pass `--jellyfin`. The container's own exit code is not visible from here: `--rm` has already
taken the container by the time a watcher could ask.

Standard library only, on the Python 3.9 floor, like everything under tools/ (010 plan D-2).

Usage:
    python3 tools/bump_reference_version.py --help
    python3 tools/bump_reference_version.py --to 10.11.12 \\
        --jellyfin http://the-new-reference:8096 --atrium http://localhost:8096 \\
        --image jellyfin/jellyfin@sha256:<the new digest>
    python3 tools/bump_reference_version.py --to 10.11.12 --jellyfin ... --dry-run
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

REPOSITORY = Path(__file__).resolve().parents[1]
TOOLS = REPOSITORY / "tools"
COMPATIBILITY = REPOSITORY / "docs" / "compatibility"
SURFACE = COMPATIBILITY / "surface.yaml"
REFERENCE_TARGET = COMPATIBILITY / "reference-target.md"
PROPERTY_NAMES = COMPATIBILITY / "property-names.json"
ATRIUM_INIT = REPOSITORY / "src" / "atrium" / "__init__.py"
REFERENCE_MODULE = TOOLS / "_reference.py"

#: Fetched documents, candidate surfaces and this command's own transcript. Git-ignored, and the
#: input to nothing: a bump writes into the repository at step 4 and nowhere else.
OUTPUT = REPOSITORY / "reference"

#: `differential.py`'s own last line. Read rather than re-derived, because the two numbers behind
#: it are what separate *a difference* from *a case the run never got to ask* - and exit `1`
#: covers both. `tests/unit/test_version_bump.py` asserts this pattern still matches the line
#: that module prints, so a rename over there fails here rather than being silently unparsed.
DIFFERENTIAL_SUMMARY = re.compile(
    r"(\d+) differences, (\d+) cases not asked, (\d+) named comparisons outstanding"
)

#: `extract_v1_surface.py` naming a row of the surface the new document no longer has. Step 1's
#: real product: *"any path or method that disappeared is a breaking change to record."*
DISAPPEARED = re.compile(r"^error: (\S+ \S+): (?:path|method) not present")

#: What `_probe.Probe.report` prints when it confirmed the documentation, and when it had no claim
#: to contradict. Both name the document the probe supports, which is what step 3 re-dates.
CONFIRMED = re.compile(r"^\s*OK\s+documentation confirmed - (\S+)\s*(.*)$")
OPEN_QUESTION = re.compile(r"^\s*open question: (\S+) ")

#: `**Last verified: 2026-09-01, against …**` at the top of a compatibility document.
LAST_VERIFIED = re.compile(r"^(\*\*Last verified:\s*)(\d{4}-\d{2}-\d{2})")

#: A version this repository would accept as a pin. `10.11.12`, never `v10.11.12` and never a tag.
VERSION = re.compile(r"^\d+\.\d+\.\d+$")

#: The image is pinned by digest and never by tag ([ADR-0007](../docs/decisions/0007-a-container-
#: runtime-for-the-reference-instance.md)), so a new version arrives with a new digest or it does
#: not arrive.
DIGEST = re.compile(r"^[\w./-]+@sha256:[0-9a-f]{64}$")


def today() -> str:
    """UTC, so a dated document means the same thing wherever it was written."""
    return datetime.now(timezone.utc).date().isoformat()


# --------------------------------------------------------------------------------------------
# Outcomes
# --------------------------------------------------------------------------------------------


class Outcome(Enum):
    """What a step answered, and there are five because collapsing any two loses a decision.

    `CHANGED` and `COULD_NOT_LOOK` are the pair that matters: the first is a measurement that
    disagrees with the documentation and wants triage into behaviours.md, the second is a run that
    measured nothing and wants running again. A command that reported both as *"step 3 failed"*
    would send a reader to triage a difference nobody observed.
    """

    PASSED = "PASSED"
    SKIPPED = "SKIPPED"
    CHANGED = "CHANGED"
    COULD_NOT_LOOK = "COULD NOT LOOK"
    LEAKED = "LEAKED"
    NOT_RUN = "NOT RUN"

    @property
    def carries_on(self) -> bool:
        """Whether the procedure may reach the next step. Only two of the six do."""
        return self in (Outcome.PASSED, Outcome.SKIPPED)


class Move(Enum):
    """Which of reference-target section 1's two rows this bump moves."""

    CONTRACT_ONLY = "the contract row alone"
    SERVER_CHANGED = "the running reference"
    UNDECIDED = "unknown"


@dataclass
class Result:
    """One step's answer: the outcome, one line, and whatever a reader needs to act on it."""

    outcome: Outcome
    summary: str
    detail: Tuple[str, ...] = ()

    @property
    def carries_on(self) -> bool:
        return self.outcome.carries_on


def stopped_here(number: int) -> Result:
    """What every step after the one that failed reports, and why it is not `SKIPPED`.

    A skipped step is a decision; a step that never ran because an earlier one failed is a hole.
    Reporting the second as the first is how *"new pin, stale readings"* gets written down as a
    completed procedure.
    """
    return Result(
        outcome=Outcome.NOT_RUN,
        summary=f"step {number} stopped the procedure, so this step never ran",
        detail=(
            "Nothing downstream may run on an input an earlier step did not produce. Fix what "
            f"step {number} reported and run the whole command again - there is no way to "
            "resume from here, deliberately.",
        ),
    )


# --------------------------------------------------------------------------------------------
# Children
# --------------------------------------------------------------------------------------------


@dataclass
class Completed:
    """A child process, as much of it as a classification needs."""

    argv: Tuple[str, ...]
    returncode: int
    stdout: str = ""
    stderr: str = ""

    @property
    def output(self) -> str:
        return self.stdout + self.stderr


Runner = Callable[[Sequence[str]], Completed]


def run_command(argv: Sequence[str]) -> Completed:
    """The default runner: this repository's own tools, by absolute path, with no shell."""
    finished = subprocess.run(  # noqa: S603 - the arguments are this module's own
        list(argv), capture_output=True, text=True
    )
    return Completed(
        argv=tuple(argv),
        returncode=finished.returncode,
        stdout=finished.stdout or "",
        stderr=finished.stderr or "",
    )


def read_running_version(url: str, timeout: int = 30) -> str:
    """The version the reference reports about itself, and a guard on what answered.

    **The guard reads the `Server` header and never `ProductName`.** Atrium answers
    `ProductName: "Jellyfin Server"` on purpose (behaviours section 4.1), so a bump pointed at
    Atrium by mistake would read its own `REFERENCE_VERSION` back, agree with the pin, decide the
    move is contract-only and skip the differential - a false bump with every step green. The
    `Server` header is `Atrium/<version>` here against the reference's `Kestrel`, which is the
    same discriminator `differential.py` uses for the same reason.
    """
    request = urllib.request.Request(  # noqa: S310 - an http(s) URL the operator passed in
        url.rstrip("/") + "/System/Info/Public", headers={"Accept": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as answer:  # noqa: S310
        header = str(answer.headers.get("Server", ""))
        body = json.loads(answer.read().decode("utf-8"))
    return version_of(url, header, body)


def version_of(url: str, server_header: str, body: Dict[str, Any]) -> str:
    """The guard and the reading, as one pure function over what a server answered.

    Pure so that it is asserted rather than described: the whole false-bump path runs through
    these four lines, and a guard that only exists inside a socket call is a guard nothing checks.
    """
    if "atrium" in server_header.lower():
        raise BumpError(
            f"the URL given as the reference answers `Server: {server_header}`. That is this "
            "project's own server: a bump measured against Atrium confirms the pin against itself"
        )
    version = str(body.get("Version", ""))
    if not version:
        raise BumpError(f"{url} answered no Version on /System/Info/Public")
    return version


class BumpError(RuntimeError):
    """The command cannot start, or cannot honestly continue. Never a finding about a server."""


# --------------------------------------------------------------------------------------------
# The pure classifications
# --------------------------------------------------------------------------------------------


def classify_move(pinned: str, running: Optional[str]) -> Move:
    """Which row moves, from a measurement and never from a flag.

    `None` is what an unreadable version arrives as, and it is `UNDECIDED` rather than either
    answer: a run that cannot see the server it is bumping to has not established that step 2 has
    no input, and *"no input"* is the only thing that excuses skipping it.
    """
    if running is None:
        return Move.UNDECIDED
    return Move.CONTRACT_ONLY if running == pinned else Move.SERVER_CHANGED


def classify_probe(returncode: int) -> Outcome:
    """A probe's exit code, in `_probe.main`'s own vocabulary.

    `3` is 010 T13's addition and it is neither of the other two: the run created something it
    could not remove and nothing explains why. It is a failure of the bump - a procedure that left
    an account behind on the server it is about to pin has not finished - and it is emphatically
    not a success because it is not `1`.
    """
    if returncode == 0:
        return Outcome.PASSED
    if returncode == 1:
        return Outcome.CHANGED
    if returncode == 3:
        return Outcome.LEAKED
    # 2 is "cannot answer the question", 130 an interrupt, and anything else is a crash. All of
    # them mean the same thing to a bump: this probe measured nothing. Fail closed.
    return Outcome.COULD_NOT_LOOK


def classify_differential(returncode: int, output: str) -> Tuple[Outcome, str]:
    """Exit `1` covers two different things, so the run's own numbers decide which it was.

    A sweep whose cases came back as connection refused - a container that died in the middle of
    it, measured on 2026-09-02 - reports **zero** differences and a pile of cases it never asked.
    That is not a reference that changed; it is a reference that stopped answering.
    """
    if returncode == 0:
        return Outcome.PASSED, "the run is clean"
    if returncode != 1:
        return Outcome.COULD_NOT_LOOK, f"differential.py could not start (exit {returncode})"
    found = DIFFERENTIAL_SUMMARY.search(output)
    if found is None:
        return (
            Outcome.COULD_NOT_LOOK,
            "differential.py exited 1 and printed no summary line, so what it compared is unknown",
        )
    differences, unasked, outstanding = (int(number) for number in found.groups())
    if differences:
        return (
            Outcome.CHANGED,
            f"{differences} untriaged difference(s), {unasked} case(s) not asked, "
            f"{outstanding} named comparison(s) outstanding",
        )
    return (
        Outcome.COULD_NOT_LOOK,
        f"no difference was found, and the run did not ask {unasked} case(s) and did not run "
        f"{outstanding} named comparison(s). Outstanding is not green",
    )


def pinned_behavioural_version(text: str) -> Optional[str]:
    """The version of reference-target section 1's **behavioural** row, which is the server's.

    The contract row moves on a document-only bump and the behavioural one does not, so reading
    the wrong row would make every move look like a server change - which is safe, and would also
    make the distinction the plan asked for a decoration.
    """
    for line in text.splitlines():
        if line.startswith("| Behavioural reference "):
            found = re.search(r"Jellyfin\s*`?(\d+\.\d+\.\d+)`?", line)
            return found.group(1) if found else None
    return None


# --------------------------------------------------------------------------------------------
# Reading the probes without importing them
# --------------------------------------------------------------------------------------------


@dataclass
class ProbeScript:
    """One `tools/probe_*.py`, and the two things a runner has to know before starting it."""

    path: Path
    writes: bool
    makes_its_own_server: bool

    @property
    def name(self) -> str:
        return self.path.name

    def argv(self, python: str, url: str) -> Tuple[str, ...]:
        line: List[str] = [python, str(self.path)]
        if not self.makes_its_own_server:
            line.append(url)
        if self.writes:
            line.append("--allow-writes")
        return tuple(line)


def read_probe(path: Path) -> ProbeScript:
    """What the script declares at its entry point, read with `ast` and never by importing it.

    Importing a probe runs its module body; `ast` reads the two keywords that decide the command
    line. `connect_with` is 010 T13's *"refuses a server argument and stands up its own
    instance"* - `probe_reference_scan.py`, `probe_public_users.py` and `probe_local_address.py`
    today - and handing one of those a URL is an immediate refusal.

    `--allow-writes` has two shapes because enforcement has two layers: a probe declares
    `needs_writes=True` at the entry point, or declares the option itself because for it the flag
    *adds a battery* rather than gating the run. Both accept the flag, which is all this needs.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    keywords: Dict[str, ast.expr] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            named = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            if named == "main":
                for keyword in node.keywords:
                    if keyword.arg:
                        keywords[keyword.arg] = keyword.value
    declares = isinstance(keywords.get("needs_writes"), ast.Constant) and bool(
        keywords["needs_writes"].value  # type: ignore[attr-defined]
    )
    own_option = any(
        isinstance(node, ast.Constant) and node.value == "--allow-writes" for node in ast.walk(tree)
    )
    return ProbeScript(
        path=path,
        writes=declares or own_option,
        makes_its_own_server="connect_with" in keywords,
    )


def probe_scripts(directory: Path = TOOLS) -> Tuple[ProbeScript, ...]:
    return tuple(read_probe(path) for path in sorted(directory.glob("probe_*.py")))


def document_supported(output: str) -> Optional[str]:
    """The document a probe said it confirmed, taken from the probe's own report.

    Read from the output rather than from the construction, because what step 3 re-dates is what
    the run actually confirmed - a probe whose finding never reached `report` has supported
    nothing, whatever its source says it bears on.
    """
    for line in output.splitlines():
        for pattern in (CONFIRMED, OPEN_QUESTION):
            found = pattern.match(line)
            if found:
                return found.group(1)
    return None


# --------------------------------------------------------------------------------------------
# Edits, which land or none of them do
# --------------------------------------------------------------------------------------------


@dataclass
class Edit:
    """One line of one file, located before anything is written.

    **A scripted edit that cannot fail is a scripted edit that will silently not happen**
    (AGENTS.md), so every edit here is located first, refuses a pattern matching zero lines or
    more than one, and is read back after writing. The set is applied all-or-nothing: five files
    hold the pinned version and a bump that moved four of them is the half-done bump this whole
    command exists to make impossible.
    """

    path: Path
    anchor: str
    old: str
    new: str
    what: str

    def locate(self, text: str) -> int:
        matching = [
            number
            for number, line in enumerate(text.splitlines())
            if re.search(self.anchor, line) and self.old in line
        ]
        if len(matching) != 1:
            raise BumpError(
                f"{_relative(self.path)}: the {self.what} line matched {len(matching)} lines, "
                "not one. The pin moved without this command, or the file changed shape - "
                "either way nothing here has been written"
            )
        return matching[0]

    def apply(self, text: str) -> str:
        number = self.locate(text)
        lines = text.splitlines(keepends=True)
        lines[number] = lines[number].replace(self.old, self.new)
        return "".join(lines)


def apply_all(edits: Sequence[Edit], write: bool = True) -> Tuple[str, ...]:
    """Locate every edit, then write, then read every file back. Returns what was done."""
    by_file: Dict[Path, List[Edit]] = {}
    for edit in edits:
        by_file.setdefault(edit.path, []).append(edit)

    planned: Dict[Path, str] = {}
    for path, group in by_file.items():
        text = path.read_text(encoding="utf-8")
        for edit in group:
            text = edit.apply(text)
        planned[path] = text

    done: List[str] = []
    if not write:
        return tuple(f"would write {edit.what} in {_relative(edit.path)}" for edit in edits)

    for path, text in planned.items():
        path.write_text(text, encoding="utf-8")

    for edit in edits:
        landed = edit.path.read_text(encoding="utf-8")
        if edit.new not in landed:
            raise BumpError(
                f"{_relative(edit.path)}: {edit.what} was written and is not in the file. "
                "Verify every scripted edit: this one reported success and did not happen"
            )
        done.append(f"{_relative(edit.path)}: {edit.what} -> {edit.new}")
    return tuple(done)


def _relative(path: Path) -> str:
    try:
        return str(path.relative_to(REPOSITORY))
    except ValueError:  # pragma: no cover - only when a caller passes an outside path
        return str(path)


def pin_edits(old: str, new: str, source_tag: str, image: str, image_now: str) -> Tuple[Edit, ...]:
    """Every machine-readable copy of the pinned version, and there are five files of them.

    Nobody had written this list down: `surface.yaml` pins the document version and the source
    tag, `property-names.json` records the document it was extracted from, `src/atrium/__init__.py`
    is the version the server *reports* to clients (reference-target section 4, which Principle I
    makes load-bearing), `tools/_reference.py` pins the image the single-use instance runs, and
    reference-target section 1 is the table all of them are supposed to agree with. Two tests
    already fail when a pair of them drift, which is how a half-done bump gets caught - after it
    has been committed.

    **The image is one value in one file and two in another.** `tools/_reference.py` builds it
    from `IMAGE_REPOSITORY` and `IMAGE_DIGEST` so the two cannot drift, and the document names the
    whole `repository@sha256:…` form. So the digest moves in the module and the full image moves
    in the table, which is why this takes both spellings rather than deriving one.
    """
    return (
        Edit(SURFACE, r"jellyfin_openapi_version:", old, new, "the pinned document version"),
        Edit(SURFACE, r"jellyfin_source_tag:", f"v{old}", source_tag, "the pinned source tag"),
        Edit(ATRIUM_INIT, r"^REFERENCE_VERSION", old, new, "the version the server reports"),
        Edit(REFERENCE_MODULE, r"^IMAGE_VERSION", old, new, "the instance image's version"),
        Edit(
            REFERENCE_MODULE,
            r"^IMAGE_DIGEST",
            image_now.split("@", 1)[1],
            image.split("@", 1)[1],
            "the instance image digest",
        ),
        Edit(REFERENCE_TARGET, r"^\| API contract ", old, new, "section 1's contract row"),
        Edit(REFERENCE_TARGET, r"^\| Behavioural reference ", old, new, "section 1's server row"),
        Edit(REFERENCE_TARGET, r"^\| Version Atrium reports ", old, new, "section 1's report row"),
        Edit(
            REFERENCE_TARGET,
            r"^\| Reference instance image ",
            image_now,
            image,
            "section 1's image row",
        ),
    )


def current_image(text: str) -> Optional[str]:
    """`tools/_reference.py`'s pinned image, rebuilt from the two constants that make it."""
    repository = re.search(r'^IMAGE_REPOSITORY\s*=\s*"([^"]+)"', text, flags=re.MULTILINE)
    digest = re.search(r'^IMAGE_DIGEST\s*=\s*"([^"]+)"', text, flags=re.MULTILINE)
    if repository is None or digest is None:
        return None
    return f"{repository.group(1)}@{digest.group(1)}"


def redate(path: Path, when: str, old: str, new: str, write: bool = True) -> str:
    """Move a document's `Last verified` line to today, and its version with it.

    Only the line itself. **The provenance tags below it are not touched**: a
    `[probe: …, Jellyfin 10.11.11, 2026-08-27]` records what was measured, when, against what, and
    rewriting the version in it would turn a measurement into a claim (Principle II). What step 3
    re-dates is the document's own header; what re-measures its citations is the probe run, one
    finding at a time.
    """
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    for number, line in enumerate(lines):
        if LAST_VERIFIED.match(line):
            moved = LAST_VERIFIED.sub(r"\g<1>" + when, line).replace(old, new)
            if not write:
                return f"would re-date {_relative(path)} to {when}"
            lines[number] = moved
            path.write_text("".join(lines), encoding="utf-8")
            landed = path.read_text(encoding="utf-8")
            if f"Last verified: {when}" not in landed:
                raise BumpError(f"{_relative(path)}: the Last verified line did not land")
            return f"{_relative(path)}: Last verified -> {when}"
    return f"{_relative(path)}: no Last verified line, left alone"


# --------------------------------------------------------------------------------------------
# The four steps
# --------------------------------------------------------------------------------------------


@dataclass
class Context:
    """Everything a step needs, and the two seams that keep the suite off the network.

    `runner` and `read_version` are injected: the tests drive all four steps, in every failing
    shape, without a Jellyfin, a container runtime or a socket - which is the only way a
    sequencer's ordering can be asserted at all (010 plan section 6.11).
    """

    args: argparse.Namespace
    runner: Runner = run_command
    read_version: Callable[[str, int], str] = read_running_version
    move: Move = Move.UNDECIDED
    #: The **behavioural** row of reference-target section 1: the version of the server every
    #: probe has been measuring. What decides the move.
    pinned: str = ""
    #: The **contract** row, which `surface.yaml` holds. Only step 1's candidate copy reads it.
    pinned_document: str = ""
    when: str = field(default_factory=today)
    document: Optional[Path] = None
    log: List[str] = field(default_factory=list)

    @property
    def python(self) -> str:
        return self.args.python or sys.executable

    def say(self, line: str) -> None:
        self.log.append(line)
        # Flushed, because the refusals go to stderr and a reader has to see the two streams in
        # the order they happened - a refusal printed above the measurement that caused it reads
        # like a different program.
        print(line, flush=True)


@dataclass
class Step:
    """One numbered step of conformance.md's procedure."""

    number: int
    title: str
    action: Callable[[Context], Result]


def step_one_the_document(context: Context) -> Result:
    """Fetch the new document and validate the surface against it.

    **The validator cannot be run against the new document with the old pin in place**, and this
    is where that was found rather than reasoned: `extract_v1_surface.py` compares the document's
    own `info.version` with `surface.yaml`'s pin and errors when they differ - measured, exit 1,
    with the version mismatch as the only error and every path check having passed. So step 1 on
    a real bump would fail at step 1, always, before it could report the thing it exists to
    report.

    The way out keeps step 4 the only writer: the surface is copied into the git-ignored output
    directory with the pin moved, and the validator is run against the **copy**. Nothing in the
    repository moves until every step has passed.
    """
    args = context.args
    document = OUTPUT / f"openapi-{args.to}.json"
    OUTPUT.mkdir(parents=True, exist_ok=True)

    fetched = context.runner(
        (
            context.python,
            str(TOOLS / "fetch_reference_spec.py"),
            args.jellyfin,
            "--out",
            str(document),
        )
    )
    if fetched.returncode != 0:
        return Result(
            Outcome.COULD_NOT_LOOK,
            f"the document could not be fetched from {args.jellyfin}",
            tuple(fetched.output.strip().splitlines()[-8:]),
        )

    if not document.exists():
        return Result(
            Outcome.COULD_NOT_LOOK,
            f"fetch_reference_spec.py exited 0 and wrote no {_relative(document)}",
        )
    context.document = document

    stated = json.loads(document.read_text(encoding="utf-8")).get("info", {}).get("version")
    if stated != args.to:
        return Result(
            Outcome.CHANGED,
            f"the document {args.jellyfin} serves says {stated!r}, and this bump claims "
            f"{args.to!r}",
            (
                "A bump names the version it is moving to and the server has to agree. Point "
                "--jellyfin at the reference you mean, or change --to.",
            ),
        )

    candidate = OUTPUT / f"surface-candidate-{args.to}.yaml"
    candidate.write_text(
        SURFACE.read_text(encoding="utf-8").replace(
            f'jellyfin_openapi_version: "{context.pinned_document}"',
            f'jellyfin_openapi_version: "{args.to}"',
        ),
        encoding="utf-8",
    )

    validated = context.runner(
        (
            context.python,
            str(TOOLS / "extract_v1_surface.py"),
            "--spec",
            str(document),
            "--surface",
            str(candidate),
            "--print-summary",
        )
    )
    if validated.returncode == 0:
        return Result(
            Outcome.PASSED,
            f"the surface is consistent with the {args.to} document",
            tuple(line for line in validated.stdout.strip().splitlines() if line),
        )

    gone = tuple(
        found.group(1)
        for found in (DISAPPEARED.match(line) for line in validated.output.splitlines())
        if found
    )
    detail = tuple(
        line for line in validated.output.strip().splitlines() if line.startswith("error")
    )
    if gone:
        return Result(
            Outcome.CHANGED,
            f"{len(gone)} endpoint(s) of the surface are not in the {args.to} document: "
            + ", ".join(gone),
            (
                *detail,
                "A path or method that disappeared is a breaking change to record before the "
                "pin moves, not an error to work around.",
            ),
        )
    return Result(
        Outcome.CHANGED, f"the surface does not validate against the {args.to} document", detail
    )


def step_two_the_differential(context: Context) -> Result:
    """The differential and the named comparisons, and the one move where it has no input.

    There is no flag here. The skip is decided by `context.move`, which was measured before step 1
    ran, because *"a bump that skips step 2 has not been done, it has been declared"* is only true
    of a command where declaring it is not among the options.
    """
    if context.move is Move.CONTRACT_ONLY:
        return Result(
            Outcome.SKIPPED,
            f"the running reference is still {context.pinned}, so only the contract row moves "
            f"and step 2 has no input",
            (
                "Nothing behavioural changed, so there is no new difference for a differential to "
                "triage; running it would compare a server against itself. conformance.md, *The "
                "two rows move separately*.",
            ),
        )

    args = context.args
    line: List[str] = [
        context.python,
        str(TOOLS / "differential.py"),
        "--atrium",
        args.atrium,
        "--jellyfin",
        args.jellyfin,
    ]
    if args.fixture:
        line.append("--fixture")
    finished = context.runner(tuple(line))
    outcome, summary = classify_differential(finished.returncode, finished.output)
    detail = tuple(finished.output.strip().splitlines()[-12:])
    if outcome is Outcome.CHANGED:
        detail = (
            *detail,
            "Every new difference is triaged into behaviours.md - replicate, diverge with an "
            "argument, or defer - by the feature that owns the endpoint, and only then is this "
            "run made again.",
        )
    elif outcome is Outcome.COULD_NOT_LOOK:
        detail = (
            *detail,
            "Nothing was measured here, so this is not a finding about the reference. The "
            "single-use instance dies with SIGILL on some starts (010 plan section 7): run it "
            "again, or stand one up with tools/reference_instance.py and pass --jellyfin.",
        )
    return Result(outcome, summary, detail)


def step_three_the_probes(context: Context) -> Result:
    """Re-run every probe, then re-date the documents the ones that passed support.

    **Every probe runs, and the step fails if any of them did not pass.** The step is the unit of
    the procedure, not the probe: the probes are independent of each other and of nothing
    downstream, so stopping at the first contradiction would cost a day per finding and buy
    nothing - where stopping the *procedure* is what the order is for. Step 4 does not run.
    """
    args = context.args
    scripts = probe_scripts()
    if not scripts:
        return Result(Outcome.COULD_NOT_LOOK, f"no probe_*.py under {_relative(TOOLS)} to run")

    outcomes: Dict[str, Outcome] = {}
    documents: List[str] = []
    lines: List[str] = []
    for script in scripts:
        finished = context.runner(script.argv(context.python, args.jellyfin))
        outcome = classify_probe(finished.returncode)
        outcomes[script.name] = outcome
        supported = document_supported(finished.output)
        if outcome is Outcome.PASSED and supported:
            documents.append(supported)
        note = f"  {outcome.value:<14} {script.name}"
        if outcome is not Outcome.PASSED:
            note += f" (exit {finished.returncode})"
        lines.append(note)
        context.say(note)

    failed = {name: outcome for name, outcome in outcomes.items() if outcome is not Outcome.PASSED}
    if failed:
        worst = (
            Outcome.LEAKED
            if Outcome.LEAKED in failed.values()
            else Outcome.CHANGED
            if Outcome.CHANGED in failed.values()
            else Outcome.COULD_NOT_LOOK
        )
        return Result(
            worst,
            f"{len(failed)} of {len(scripts)} probes did not pass",
            (
                *lines,
                "A contradiction is the reference disagreeing with a document, and it is "
                "recorded there - with both dates, if the behaviour changed rather than the "
                "claim being wrong. A probe that could not look measured nothing. A leak left "
                "something on the server and has to be removed by hand.",
            ),
        )

    re_dated = [
        redate(REPOSITORY / name, context.when, context.pinned, args.to, write=not args.dry_run)
        for name in sorted(set(documents))
        if (REPOSITORY / name).exists()
    ]
    for line in re_dated:
        context.say(f"  {line}")
    return Result(
        Outcome.PASSED,
        f"all {len(scripts)} probes confirmed the documentation",
        tuple(lines) + tuple(re_dated),
    )


def step_four_the_pin(context: Context) -> Result:
    """Write the version, in every file that holds it, or in none of them.

    The last step because it is the only one that changes the repository, and all-or-nothing
    because the pin lives in five files: a bump that moved four of them is the *"new pin, stale
    readings"* this procedure exists to prevent, wearing a green tick.
    """
    args = context.args
    image_now = current_image(REFERENCE_MODULE.read_text(encoding="utf-8"))
    if image_now is None:
        return Result(Outcome.COULD_NOT_LOOK, f"{_relative(REFERENCE_MODULE)} pins no image")
    if image_now.split("@", 1)[0] != str(args.image).split("@", 1)[0]:
        return Result(
            Outcome.COULD_NOT_LOOK,
            f"--image names {str(args.image).split('@', 1)[0]} where the instance pins "
            f"{image_now.split('@', 1)[0]}. Which image the reference *is* belongs to ADR-0007 "
            f"and not to a version bump",
        )

    edits = pin_edits(context.pinned, args.to, args.source_tag, args.image, image_now)
    try:
        done = apply_all(edits, write=not args.dry_run)
    except BumpError as failure:
        return Result(Outcome.COULD_NOT_LOOK, str(failure))

    if args.dry_run:
        return Result(Outcome.PASSED, f"would write the pin in {len(edits)} places", tuple(done))

    if context.document is not None:
        regenerated = context.runner(
            (
                context.python,
                str(TOOLS / "extract_property_names.py"),
                "--spec",
                str(context.document),
                "--index",
                str(PROPERTY_NAMES),
            )
        )
        if regenerated.returncode != 0:
            return Result(
                Outcome.COULD_NOT_LOOK,
                "the property-name index could not be regenerated from the new document",
                tuple(regenerated.output.strip().splitlines()[-8:]),
            )
        done = (*done, f"{_relative(PROPERTY_NAMES)}: regenerated from the {args.to} document")

        confirmed = context.runner(
            (
                context.python,
                str(TOOLS / "extract_v1_surface.py"),
                "--spec",
                str(context.document),
                "--print-summary",
            )
        )
        if confirmed.returncode != 0:
            return Result(
                Outcome.COULD_NOT_LOOK,
                "the pin was written and the surface no longer validates against the document",
                tuple(confirmed.output.strip().splitlines()[-8:]),
            )
    return Result(Outcome.PASSED, f"the pin is {args.to} in {len(edits)} places", tuple(done))


def steps() -> Tuple[Step, ...]:
    """conformance.md's four, in its order, which is the whole product."""
    return (
        Step(1, "Fetch the new document; validate the surface", step_one_the_document),
        Step(2, "Run the differential and the named comparisons", step_two_the_differential),
        Step(3, "Re-run every probe; re-date what they support", step_three_the_probes),
        Step(4, "Write the pinned version", step_four_the_pin),
    )


def procedure(context: Context) -> List[Tuple[Step, Result]]:
    """Run the steps in order, and stop dead at the first one that does not carry on.

    The half that catches a sequencer which reports a failure and carries on anyway is the second
    loop: every remaining step is recorded NOT RUN, by name, so the transcript says which parts of
    the procedure did not happen instead of ending at the failure.
    """
    done: List[Tuple[Step, Result]] = []
    ordered = steps()
    for position, step in enumerate(ordered):
        result = step.action(context)
        done.append((step, result))
        context.say(f"step {step.number}: {result.outcome.value} - {result.summary}")
        for line in result.detail:
            context.say(f"    {line}")
        if not result.carries_on:
            for later in ordered[position + 1 :]:
                stopped = stopped_here(step.number)
                done.append((later, stopped))
                context.say(f"step {later.number}: {stopped.outcome.value} - {stopped.summary}")
            break
    return done


# --------------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bump_reference_version.py",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Move the pinned Jellyfin version, by running conformance.md's four steps in order "
            "and refusing to continue past a failure. A bump that skips step 2 has not been "
            "done, it has been declared - so there is no flag that skips it."
        ),
        epilog=(
            "Exit codes: 0 the pin moved, 1 a step stopped the procedure, 2 the command could "
            "not start.\n"
            "No CI job runs this: it contacts a Jellyfin, and no job may (ADR-0007).\n"
            "Whether step 2 runs is measured, not declared: the reference is asked its own "
            "version and compared with the behavioural row of reference-target section 1."
        ),
    )
    parser.add_argument("--to", help="The version being pinned, e.g. 10.11.12")
    parser.add_argument("--jellyfin", help="Base URL of the reference this bump moves to")
    parser.add_argument(
        "--atrium",
        help="Base URL of the Atrium the differential compares against. Required when the "
        "running reference changed, because step 2 is then mandatory",
    )
    parser.add_argument(
        "--source-tag",
        help="The Jellyfin source tag for --to. Defaults to v<version>",
    )
    parser.add_argument(
        "--image",
        help="The new reference image, pinned by digest: jellyfin/jellyfin@sha256:<64 hex>. A "
        "version this repository has not stood up is a version it has not measured",
    )
    parser.add_argument(
        "--fixture",
        action="store_true",
        help="Ask the differential's fixture half too, which stands up a single-use instance",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Classify the move and print what each step would run. Writes nothing, anywhere",
    )
    parser.add_argument("--python", help="Interpreter for the child tools. Defaults to this one")
    parser.add_argument(
        "--timeout", type=int, default=30, help="Seconds to wait for the reference's own version"
    )
    return parser


def prepare(args: argparse.Namespace, context: Context) -> None:
    """Everything that has to hold before step 1, checked before step 1.

    Refusing here rather than three steps in is the same rule the steps themselves obey: a
    procedure that discovers at step 4 that it never had a digest to write has run the whole thing
    for nothing, and a procedure that discovers at step 2 that it has no Atrium has already
    fetched a document it will not use.
    """
    if not args.to or not VERSION.match(args.to):
        raise BumpError("--to is the version being pinned, in the form 10.11.12")
    if not args.jellyfin:
        raise BumpError("--jellyfin is the reference this bump moves to")
    args.source_tag = args.source_tag or f"v{args.to}"

    pinned_text = REFERENCE_TARGET.read_text(encoding="utf-8")
    behavioural = pinned_behavioural_version(pinned_text)
    if behavioural is None:
        raise BumpError(
            f"{_relative(REFERENCE_TARGET)} section 1 has no behavioural row to compare against"
        )
    context.pinned = behavioural
    context.pinned_document = _pinned_document()

    try:
        running: Optional[str] = context.read_version(args.jellyfin, args.timeout)
    except BumpError:
        raise
    except (OSError, ValueError, urllib.error.URLError) as failure:
        context.say(f"the reference at {args.jellyfin} could not be asked its version: {failure}")
        running = None
    context.move = classify_move(behavioural, running)

    if context.move is Move.UNDECIDED:
        raise BumpError(
            "the running reference did not answer its version, so which of the two rows this "
            "bump moves is unknown. That is not contract-only: a bump that cannot see the server "
            "it is pinning has not established that step 2 has no input. Fix the connection and "
            "run it again"
        )
    context.say(
        f"the reference answers {running} and the behavioural row pins {behavioural}: "
        f"this bump moves {context.move.value}"
    )
    if context.move is Move.SERVER_CHANGED and not args.atrium:
        raise BumpError(
            "the running reference changed, so step 2 is mandatory and it needs an Atrium to "
            "compare against: pass --atrium"
        )
    if not args.dry_run and (not args.image or not DIGEST.match(args.image)):
        raise BumpError(
            "--image is the new reference image pinned by digest, and it is required: the "
            "single-use instance runs the pinned version, and a version with no image is one "
            "this repository cannot stand up (ADR-0007)"
        )


def _pinned_document() -> str:
    found = re.search(r'jellyfin_openapi_version:\s*"([^"]+)"', SURFACE.read_text(encoding="utf-8"))
    if found is None:
        raise BumpError(f"{_relative(SURFACE)} pins no document version")
    return found.group(1)


def transcript(context: Context, done: Sequence[Tuple[Step, Result]]) -> str:
    lines = [
        f"# Reference version bump to {context.args.to}",
        "",
        f"- date: {context.when}",
        f"- reference: {context.args.jellyfin}",
        f"- move: {context.move.value}",
        "",
        "| Step | | Outcome |",
        "|---|---|---|",
    ]
    for step, result in done:
        lines.append(f"| {step.number} | {step.title} | **{result.outcome.value}** |")
    lines.extend(["", "```", *context.log, "```", ""])
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    context = Context(args=args)
    try:
        prepare(args, context)
    except BumpError as failure:
        print(f"bump_reference_version.py: {failure}", file=sys.stderr)
        return 2
    except OSError as failure:
        print(f"bump_reference_version.py: {failure}", file=sys.stderr)
        return 2

    if args.dry_run:
        context.say("--dry-run: nothing below is executed and nothing is written")
        for step in steps():
            skipped = step.number == 2 and context.move is Move.CONTRACT_ONLY
            would = "would be SKIPPED - only the contract row moves" if skipped else "would run"
            context.say(f"step {step.number}: {would} - {step.title}")
        return 0

    done = procedure(context)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    destination = OUTPUT / f"bump-{args.to}-{context.when}.md"
    destination.write_text(transcript(context, done), encoding="utf-8")
    print(f"bump_reference_version.py: transcript written to {_relative(destination)}")
    return 0 if all(result.carries_on for _, result in done) else 1


if __name__ == "__main__":
    raise SystemExit(main())
