# SPDX-License-Identifier: GPL-3.0-or-later
"""The version bump is an order, so what is asserted is the order — 010 T14, AC-12.

`tools/bump_reference_version.py` adds no mechanism: every step it runs is a program that already
exists. What it adds is the sequence, and a sequence is exactly the kind of thing that looks right
and is not. So each of the four steps is made to fail in turn, and each failure is asserted twice:
that the command **stopped**, and that **the later steps did not run**. The second half is the one
that catches a sequencer which reports a failure and carries on — the shape of *"a bump that skips
step 2 has not been done, it has been declared"*, wearing a green tick.

Three properties beyond the ordering are asserted here because the command's honesty rests on
them, and none of them is visible by reading it:

* **No flag skips step 2 when the running reference changed.** Asserted by trying *every* option
  the parser has, one at a time, rather than by trying the ones somebody thought of. Add a
  `--skip-differential` that works and this test fails on it without being edited.
* **A dead container is not a changed reference.** The three probes that stand up their own
  instance convert an `InstanceError` into a `ProbeError`, which is what makes `_probe.main`
  answer `2` — *it could not look* — rather than letting the exception escape and exit `1`, which
  is the code a **contradiction** uses. The classification the bump performs is only as good as
  that conversion, so the conversion is asserted on every probe that makes its own server.
* **`differential.py`'s summary line is parseable.** Exit `1` from that program covers a
  difference it found *and* a case it never asked, and the two are the same distinction again: one
  is a finding about the reference, the other is a run that measured nothing. The bump reads the
  line to tell them apart, so this file fails if the line is renamed over there.

No server, no socket, no container, no subprocess: the runner and the version reader are the two
seams `Context` exists to hold, and every test here injects both. The file edits are driven over
`tmp_path` copies, except the ones deliberately driven against the real repository under
`--dry-run`, which writes nothing anywhere — that is what proves the nine pins are locatable in
the files this repository actually ships.
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"


def _load() -> Any:
    """`tools/` is a directory of standalone programs, not an importable package.

    Registered in `sys.modules` before it executes, because the module declares dataclasses and
    `dataclasses` resolves a field's annotation by looking its defining module up by name — the
    same line `tests/conformance/test_differential.py` had to add for the engine.
    """
    name = "atrium_version_bump"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, TOOLS / "bump_reference_version.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


bump = _load()


# --------------------------------------------------------------------------------------------
# A fake child, and a context that runs no child at all
# --------------------------------------------------------------------------------------------


class Runner:
    """Answers each child by the name of the tool it is, and records what it was asked.

    Keyed on the tool's file name rather than on the whole command line, because what a test
    wants to say is *"the differential failed"*, and how the bump spells its arguments is the
    thing under test rather than an input to it.
    """

    #: What a successful fetch leaves behind, since step 1 reads the document it asked for.
    document: Path | None = None

    def __init__(self, **answers: tuple[int, str]) -> None:
        self.answers: dict[str, tuple[int, str]] = dict(answers)
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, argv: Sequence[str]) -> Any:
        self.calls.append(tuple(argv))
        tool = Path(argv[1]).stem if len(argv) > 1 else ""
        code, output = self.answers.get(tool, (0, ""))
        if tool == "fetch_reference_spec" and code == 0 and self.document is not None:
            self.document.parent.mkdir(parents=True, exist_ok=True)
            self.document.write_text(
                '{"info": {"version": "10.11.12"}, "paths": {}}', encoding="utf-8"
            )
        return bump.Completed(argv=tuple(argv), returncode=code, stdout=output)

    def ran(self, tool: str) -> bool:
        return any(len(call) > 1 and Path(call[1]).stem == tool for call in self.calls)

    @property
    def tools(self) -> list[str]:
        return [Path(call[1]).stem for call in self.calls if len(call) > 1]


def namespace(**overrides: Any) -> argparse.Namespace:
    """The arguments a real bump carries, so a test overrides one thing and not eleven."""
    args = argparse.Namespace(
        to="10.11.12",
        jellyfin="http://reference:8096",
        atrium="http://localhost:8096",
        source_tag="v10.11.12",
        image="jellyfin/jellyfin@sha256:" + "b" * 64,
        fixture=False,
        dry_run=False,
        python=sys.executable,
        timeout=30,
    )
    for key, value in overrides.items():
        setattr(args, key, value)
    return args


def context(runner: Runner, **overrides: Any) -> Any:
    """A context whose move has already been classified, so a test can drive the steps alone."""
    return bump.Context(
        args=namespace(**overrides.pop("args", {})),
        runner=runner,
        read_version=lambda url, timeout=30: "10.11.12",
        move=overrides.pop("move", bump.Move.SERVER_CHANGED),
        pinned=overrides.pop("pinned", "10.11.11"),
        pinned_document=overrides.pop("pinned_document", "10.11.11"),
        when=overrides.pop("when", "2026-09-02"),
    )


# --------------------------------------------------------------------------------------------
# The four steps, each made to fail in turn
# --------------------------------------------------------------------------------------------


def _all_pass(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, **failures: tuple[int, str]) -> Any:
    """A procedure whose four steps all pass, except the ones a test breaks.

    Step 1 writes a document and a candidate surface, so the output directory is redirected into
    `tmp_path`: a test must not leave a fetched document in the developer's own `reference/`.
    """
    monkeypatch.setattr(bump, "OUTPUT", tmp_path / "reference")
    runner = Runner(**failures)
    runner.document = tmp_path / "reference" / "openapi-10.11.12.json"
    return runner


def _procedure(runner: Runner, **overrides: Any) -> list[tuple[Any, Any]]:
    return bump.procedure(context(runner, **overrides))


def _outcomes(done: Sequence[tuple[Any, Any]]) -> dict[int, Any]:
    return {step.number: result.outcome for step, result in done}


def test_all_four_steps_run_in_order_when_each_one_passes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The control case, without which every assertion below passes by running nothing."""
    runner = _all_pass(monkeypatch, tmp_path)
    monkeypatch.setattr(bump, "probe_scripts", lambda *_: (_probe_script(tmp_path),))
    done = _procedure(runner, args={"dry_run": True})
    assert _outcomes(done) == dict.fromkeys((1, 2, 3, 4), bump.Outcome.PASSED)
    assert runner.tools[:2] == ["fetch_reference_spec", "extract_v1_surface"]
    assert runner.tools.index("differential") < runner.tools.index("probe_example")


@pytest.mark.parametrize(
    ("failing", "answers"),
    [
        (1, {"extract_v1_surface": (1, "error: GET /System/Info/Public: path not present")}),
        (2, {"differential": (1, "1 differences, 0 cases not asked, 0 named comparisons out")}),
        (3, {"probe_example": (1, "")}),
        (4, {}),
    ],
    ids=["step-1-the-document", "step-2-the-differential", "step-3-the-probes", "step-4-the-pin"],
)
def test_a_failed_step_stops_the_procedure_and_the_later_steps_do_not_run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    failing: int,
    answers: dict[str, tuple[int, str]],
) -> None:
    """Each step made to fail in turn, asserting the stop **and** the silence after it.

    The second assertion is the one that matters. A sequencer that prints a failure and runs the
    rest of the procedure anyway passes the first: the failure is in the output, the reader sees
    it, and the pin moved regardless. So every later step must be `NOT RUN` — the outcome that
    exists to be distinguishable from `SKIPPED`, which is a decision rather than a hole — and no
    tool belonging to a later step may appear in the runner's record at all.
    """
    runner = _all_pass(monkeypatch, tmp_path, **answers)
    monkeypatch.setattr(bump, "probe_scripts", lambda *_: (_probe_script(tmp_path),))
    if failing == 4:
        # Step 4's failure is a pin that cannot be located, which is the shape a bump takes when
        # somebody has already moved one of the five files by hand.
        monkeypatch.setattr(bump, "SURFACE", tmp_path / "not-a-surface.yaml")
        (tmp_path / "not-a-surface.yaml").write_text("nothing here\n", encoding="utf-8")

    done = _procedure(runner, args={"dry_run": True})
    outcomes = _outcomes(done)

    assert outcomes[failing] is not bump.Outcome.PASSED, (
        f"step {failing} was made to fail and reported {outcomes[failing]}"
    )
    for later in range(failing + 1, 5):
        assert outcomes[later] is bump.Outcome.NOT_RUN, (
            f"step {failing} failed and step {later} reported {outcomes[later]}. Nothing "
            f"downstream may run on an input an earlier step did not produce - a sequencer that "
            f"reports a failure and carries on is the whole failure mode this command exists to "
            f"prevent."
        )
    later_tools = {2: "differential", 3: "probe_example"}
    for number, tool in later_tools.items():
        if number > failing:
            assert not runner.ran(tool), f"{tool} ran after step {failing} had failed"


def _probe_script(directory: Path) -> Any:
    path = directory / "probe_example.py"
    path.write_text("# a stand-in\n", encoding="utf-8")
    return bump.ProbeScript(path=path, writes=False, makes_its_own_server=False)


# --------------------------------------------------------------------------------------------
# Step 2 is mandatory, and no flag says otherwise
# --------------------------------------------------------------------------------------------


def _flags() -> list[str]:
    options = []
    for action in bump.build_parser()._actions:
        options.extend(option for option in action.option_strings if option not in ("-h", "--help"))
    return options


def test_there_are_flags_to_try() -> None:
    """Without this, the sweep below passes by iterating over nothing."""
    assert len(_flags()) > 5, f"the parser has {len(_flags())} options to try"


@pytest.mark.parametrize("flag", _flags())
def test_no_flag_skips_step_two_when_the_running_reference_changed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, flag: str
) -> None:
    """Every option the parser has, one at a time, against a move that changed the server.

    Tried exhaustively rather than by name, because the flags that would need testing are the
    ones nobody thought of. The guard is one line — step 2 skips on `context.move` and on nothing
    else — and deleting it means honouring some argument instead, which this finds whatever the
    argument is called.

    `--dry-run` is the one option that legitimately runs nothing at all, so what is asserted for
    it is that step 2 is still **planned** rather than skipped: it is a way to see the procedure,
    never a smaller version of it.
    """
    runner = _all_pass(monkeypatch, tmp_path)
    monkeypatch.setattr(bump, "probe_scripts", lambda *_: (_probe_script(tmp_path),))
    overrides: dict[str, Any] = {"dry_run": True}
    name = flag.lstrip("-").replace("-", "_")
    if name in ("to", "jellyfin", "atrium", "source_tag", "image", "python", "timeout"):
        pass  # a value-carrying option: its value cannot make step 2 optional either
    else:
        overrides[name] = True

    done = _procedure(runner, args=overrides)
    outcomes = _outcomes(done)
    assert outcomes[2] is not bump.Outcome.SKIPPED, (
        f"{flag} skipped step 2 on a bump where the running reference changed. A bump that skips "
        f"step 2 has not been done, it has been declared - and the skip is a measurement, never "
        f"an argument."
    )
    assert runner.ran("differential"), f"{flag} kept the differential from running"


def test_step_two_is_skipped_when_only_the_contract_row_moves(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The other half of the same rule, which is the move actually made on 2026-09-01.

    A document-only bump has no new server, so step 2 has no input and running it would compare a
    server against itself. Skipped is a decision and it is reported as one — and the three other
    steps still run in full.
    """
    runner = _all_pass(monkeypatch, tmp_path)
    monkeypatch.setattr(bump, "probe_scripts", lambda *_: (_probe_script(tmp_path),))
    done = _procedure(runner, move=bump.Move.CONTRACT_ONLY, args={"dry_run": True})
    outcomes = _outcomes(done)
    assert outcomes[2] is bump.Outcome.SKIPPED
    assert not runner.ran("differential")
    assert outcomes[1] is bump.Outcome.PASSED
    assert outcomes[3] is bump.Outcome.PASSED
    assert outcomes[4] is bump.Outcome.PASSED


@pytest.mark.parametrize(
    ("pinned", "running", "expected"),
    [
        ("10.11.11", "10.11.11", "CONTRACT_ONLY"),
        ("10.11.11", "10.11.12", "SERVER_CHANGED"),
        ("10.11.11", None, "UNDECIDED"),
    ],
)
def test_the_move_is_classified_from_the_servers_own_answer(
    pinned: str, running: Any, expected: str
) -> None:
    """And an unreadable version is `UNDECIDED`, which is neither of the other two.

    This is the false-bump path and it is one line wide: a run that cannot see the server it is
    pinning has not established that step 2 has no input, and *"no input"* is the only thing that
    excuses skipping the step the whole procedure is about. Fail closed.
    """
    assert bump.classify_move(pinned, running) is getattr(bump.Move, expected)


def test_an_unreadable_version_refuses_to_start_rather_than_assuming_contract_only(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The refusal, at the command's own boundary, before a single step has run."""

    def unreachable(url: str, timeout: int = 30) -> str:
        raise OSError("connection refused")

    ctx = bump.Context(args=namespace(), read_version=unreachable)
    with pytest.raises(bump.BumpError) as refusal:
        bump.prepare(ctx.args, ctx)
    assert "not contract-only" in str(refusal.value)


def test_a_reference_url_answering_as_atrium_is_refused() -> None:
    """A bump measured against Atrium would confirm the pin against itself.

    `ProductName` cannot make this distinction — Atrium answers `"Jellyfin Server"` there on
    purpose (behaviours §4.1), so a bump pointed at Atrium by mistake would read Atrium's own
    `REFERENCE_VERSION` back, find it equal to the pin, call the move contract-only and skip the
    differential: four green steps over a server that agreed with every claim because it is the
    thing that makes them. The guard reads the `Server` header, which is the discriminator
    `differential.py` uses for the same reason.
    """
    with pytest.raises(bump.BumpError) as refusal:
        bump.version_of("http://localhost:8096", "Atrium/0.1.0", {"Version": "10.11.11"})
    assert "Atrium" in str(refusal.value)

    assert bump.version_of("http://x", "Kestrel", {"Version": "10.11.12"}) == "10.11.12"
    with pytest.raises(bump.BumpError):
        bump.version_of("http://x", "Kestrel", {})


# --------------------------------------------------------------------------------------------
# A changed reference against a container that died
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (0, "PASSED"),
        (1, "CHANGED"),
        (2, "COULD_NOT_LOOK"),
        (3, "LEAKED"),
        (130, "COULD_NOT_LOOK"),
        (137, "COULD_NOT_LOOK"),
    ],
)
def test_a_probes_exit_code_is_classified_in_probe_mains_own_vocabulary(
    code: int, expected: str
) -> None:
    """`3` is neither a finding nor a success, and everything unknown fails closed.

    010 T13 added `3`: the run created something it could not remove and nothing explains why. A
    bump that treated it as success because it is not `1` would pin a version having left an
    account behind on the server it just pinned.
    """
    assert bump.classify_probe(code) is getattr(bump.Outcome, expected)


@pytest.mark.parametrize(
    ("code", "output", "expected"),
    [
        (0, "", "PASSED"),
        (
            1,
            "differential.py: 3 differences, 0 cases not asked, 0 named comparisons outstanding.",
            "CHANGED",
        ),
        (
            1,
            "differential.py: 0 differences, 41 cases not asked, 6 named comparisons outstanding.",
            "COULD_NOT_LOOK",
        ),
        (1, "differential.py: something else entirely", "COULD_NOT_LOOK"),
        (2, "", "COULD_NOT_LOOK"),
    ],
)
def test_the_differential_is_classified_from_its_own_numbers_and_not_its_exit_code(
    code: int, output: str, expected: str
) -> None:
    """Exit `1` covers a difference found and a case never asked, and they are opposite findings.

    A container that dies in the middle of a sweep — measured on 2026-09-02, one of four deaths in
    eight starts — brings every remaining case back as a connection refused, which the harness
    reports as **not asked**. Zero differences and forty-one unasked cases is not a reference that
    changed; it is a reference that stopped answering, and the remedy is to run it again rather
    than to triage anything.
    """
    outcome, _ = bump.classify_differential(code, output)
    assert outcome is getattr(bump.Outcome, expected)


def test_the_summary_line_this_reads_is_the_line_differential_prints() -> None:
    """The coupling between two tools, asserted rather than hoped for.

    The classification above is a regex over another program's output. Rename that line and the
    bump silently stops being able to tell a difference from an unasked case — it would fall back
    to *"could not look"* on every unclean run, which is the safe direction and still wrong.
    """
    source = (TOOLS / "differential.py").read_text(encoding="utf-8")
    # Adjacent string literals are joined the way Python joins them, because the line is written
    # across three of them over there and a fragment check against the raw source would look for
    # `" cases not asked, "` where the file holds `" cases not "` and `"asked, "`.
    joined = re.sub(r'"\s*\n\s*f?"', "", source)
    for fragment in (" differences, ", " cases not asked, ", " named comparisons outstanding."):
        assert fragment in joined, (
            f"tools/differential.py no longer prints {fragment!r}, so "
            f"bump_reference_version.py's DIFFERENTIAL_SUMMARY cannot read its report"
        )
    rebuilt = "differential.py: 2 differences, 3 cases not asked, 4 named comparisons outstanding."
    assert bump.DIFFERENTIAL_SUMMARY.search(rebuilt) is not None


def _makes_its_own_server(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return any(
        isinstance(node, ast.Call)
        and any(keyword.arg == "connect_with" for keyword in node.keywords)
        for node in ast.walk(tree)
    )


def _instance_probes() -> list[Path]:
    return [path for path in sorted(TOOLS.glob("probe_*.py")) if _makes_its_own_server(path)]


def test_there_are_probes_that_make_their_own_instance() -> None:
    """Three today. A sweep over none would assert nothing at all."""
    assert len(_instance_probes()) >= 3, (
        f"{len(_instance_probes())} probes stand up their own instance; T13 records three"
    )


@pytest.mark.parametrize("path", _instance_probes(), ids=lambda path: path.name)
def test_a_probe_that_makes_its_own_instance_turns_a_dead_container_into_could_not_look(
    path: Path,
) -> None:
    """The contract the whole *changed versus died* distinction rests on.

    `_reference.InstanceError` is not a `ProbeError`, and `_probe.main` catches only the second.
    An instance that dies with `SIGILL` — four of eight starts on 2026-09-02 — surfaces as a
    readiness timeout, so a probe that lets that exception escape exits `1` on the traceback: the
    exact code a **contradiction** uses. The bump would then report *the reference changed* about
    a reading nobody took, and a human would go looking in behaviours.md for a difference that
    does not exist.

    All three convert it, and this is what keeps them doing so.
    """
    source = path.read_text(encoding="utf-8")
    assert "InstanceError" in source and "ProbeError" in source, (
        f"tools/{path.name} stands up its own instance and never mentions InstanceError. An "
        f"instance that dies raises one, it is not a ProbeError, and _probe.main catches only "
        f"ProbeError - so the container's death would exit 1 and read as a contradiction."
    )
    tree = ast.parse(source, filename=str(path))
    converts = any(
        isinstance(node, ast.ExceptHandler)
        and "InstanceError" in ast.dump(node.type)
        and any(
            isinstance(inner, ast.Raise) and "ProbeError" in ast.dump(inner)
            for inner in ast.walk(node)
        )
        for node in ast.walk(tree)
    )
    assert converts, (
        f"tools/{path.name} does not raise a ProbeError from an InstanceError. A dead container "
        f"has to reach the bump as exit 2 - it could not look - and never as exit 1."
    )


# --------------------------------------------------------------------------------------------
# Reading the probes, and re-dating what they support
# --------------------------------------------------------------------------------------------


def test_a_probe_that_makes_its_own_server_is_handed_no_url() -> None:
    """T13: three probes refuse a server argument, and handing one a URL is a refusal.

    Step 3 runs every probe there is, so the command line it builds is per probe and not one
    template. It is read from the script with `ast` rather than by importing it, because importing
    a probe runs its module body.
    """
    scripts = {script.name: script for script in bump.probe_scripts()}
    assert scripts["probe_reference_scan.py"].makes_its_own_server is True
    assert scripts["probe_public_users.py"].makes_its_own_server is True
    assert scripts["probe_local_address.py"].makes_its_own_server is True

    argv = scripts["probe_reference_scan.py"].argv("python3", "http://reference:8096")
    assert "http://reference:8096" not in argv, (
        "probe_reference_scan.py refuses a server argument: it measures only an instance it "
        "creates and destroys itself, never a server somebody owns"
    )
    ordinary = scripts["probe_public_info.py"].argv("python3", "http://reference:8096")
    assert ordinary[-1] == "http://reference:8096"


def test_a_writing_probe_is_given_the_flag_that_gates_its_writes() -> None:
    """Both shapes of the declaration, because enforcement has two layers.

    A probe declares `needs_writes=True` at the entry point, or declares `--allow-writes` itself
    because for it the flag adds a battery rather than gating the run (T13). A bump that omitted
    the flag would get exit `2` from every writing probe and read the whole step as *could not
    look*, which is a procedure that can never complete.
    """
    scripts = {script.name: script for script in bump.probe_scripts()}
    assert scripts["probe_playlist_creation.py"].writes is True
    assert "--allow-writes" in scripts["probe_playlist_creation.py"].argv("python3", "http://x")
    assert scripts["probe_playback_info.py"].writes is True


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        (
            "  OK  documentation confirmed - docs/compatibility/behaviours.md §2.2",
            "docs/compatibility/behaviours.md",
        ),
        (
            "  open question: specs/010-conformance-harness/spec.md §3.1 has no claim",
            "specs/010-conformance-harness/spec.md",
        ),
        ("  CONTRADICTION", None),
    ],
)
def test_the_document_a_probe_supports_is_read_from_its_own_report(
    line: str, expected: Any
) -> None:
    """What step 3 re-dates is what the run confirmed, not what the source says it bears on."""
    assert bump.document_supported(line) == expected


def test_re_dating_moves_the_header_and_leaves_every_citation_alone(tmp_path: Path) -> None:
    """A `Last verified` line is a claim about a run; a provenance tag is a record of one.

    Rewriting `[probe: …, Jellyfin 10.11.11, 2026-08-27]` to name the new version would turn a
    measurement into a claim — Principle II — so the version is moved on the header line and
    nowhere else. What re-measures a citation is the probe run, one finding at a time.
    """
    document = tmp_path / "behaviours.md"
    document.write_text(
        "# Behaviours\n\n"
        "**Last verified: 2026-08-28, against Jellyfin 10.11.11.**\n\n"
        "Something `[probe: tools/probe_x.py, Jellyfin 10.11.11, 2026-08-27]`.\n",
        encoding="utf-8",
    )
    said = bump.redate(document, "2026-09-02", "10.11.11", "10.11.12")
    landed = document.read_text(encoding="utf-8")

    assert "**Last verified: 2026-09-02, against Jellyfin 10.11.12.**" in landed
    assert "[probe: tools/probe_x.py, Jellyfin 10.11.11, 2026-08-27]" in landed
    assert "2026-09-02" in said


def test_a_document_with_no_last_verified_line_is_left_alone(tmp_path: Path) -> None:
    """Most of what a probe names is a `spec.md`, which dates itself in its frontmatter."""
    document = tmp_path / "spec.md"
    document.write_text("---\nstatus: Accepted\n---\n\n# A spec\n", encoding="utf-8")
    said = bump.redate(document, "2026-09-02", "10.11.11", "10.11.12")
    assert "no Last verified line" in said
    assert document.read_text(encoding="utf-8").startswith("---\nstatus: Accepted")


# --------------------------------------------------------------------------------------------
# The pin, in every place that holds it or in none of them
# --------------------------------------------------------------------------------------------


def test_every_pin_this_step_writes_is_locatable_in_the_files_that_ship_today() -> None:
    """Nine edits over five files, located against the real repository and writing nothing.

    The pinned version is not in one place: `surface.yaml` holds the document version and the
    source tag, `src/atrium/__init__.py` the version the server reports to clients,
    `tools/_reference.py` the image and its version, and reference-target §1 the table all of them
    are supposed to agree with. A bump that moved four of the five is the *"new pin, stale
    readings"* half-done bump — so this asserts every one of them is findable, exactly once, in
    the files as they are.
    """
    image_now = bump.current_image(bump.REFERENCE_MODULE.read_text(encoding="utf-8"))
    assert image_now is not None and image_now.startswith("jellyfin/jellyfin@sha256:")
    edits = bump.pin_edits(
        old="10.11.11",
        new="10.11.12",
        source_tag="v10.11.12",
        image="jellyfin/jellyfin@sha256:" + "c" * 64,
        image_now=image_now,
    )
    assert len(edits) == 9
    for edit in edits:
        edit.locate(edit.path.read_text(encoding="utf-8"))

    for edit in edits:
        assert edit.path.read_text(encoding="utf-8").count("10.11.12") == 0, (
            f"{edit.path} was written to by a test that must write nothing"
        )


def test_an_edit_that_matches_nothing_refuses_and_writes_none_of_the_others(
    tmp_path: Path,
) -> None:
    """All-or-nothing, because a partial pin is the failure this command exists to prevent.

    *"A scripted edit that cannot fail is a scripted edit that will silently not happen"* — so the
    location of every edit happens before the first byte is written, and one that matches zero
    lines takes the whole set down with it.
    """
    good = tmp_path / "surface.yaml"
    good.write_text('jellyfin_openapi_version: "10.11.11"\n', encoding="utf-8")
    bad = tmp_path / "__init__.py"
    bad.write_text("REFERENCE_VERSION = 'moved by hand'\n", encoding="utf-8")

    edits = (
        bump.Edit(good, r"jellyfin_openapi_version:", "10.11.11", "10.11.12", "the document"),
        bump.Edit(bad, r"^REFERENCE_VERSION", "10.11.11", "10.11.12", "the reported version"),
    )
    with pytest.raises(bump.BumpError) as refusal:
        bump.apply_all(edits)
    assert "matched 0 lines" in str(refusal.value)
    assert good.read_text(encoding="utf-8") == 'jellyfin_openapi_version: "10.11.11"\n', (
        "the first edit was written before the second one was found to be unlocatable, which is "
        "the half-done bump in miniature"
    )


def test_an_ambiguous_edit_is_refused_rather_than_applied_to_the_first_match(
    tmp_path: Path,
) -> None:
    """Two matching lines mean the file changed shape, and guessing between them is not a bump."""
    path = tmp_path / "surface.yaml"
    path.write_text(
        'jellyfin_openapi_version: "10.11.11"\njellyfin_openapi_version: "10.11.11"\n',
        encoding="utf-8",
    )
    edit = bump.Edit(path, r"jellyfin_openapi_version:", "10.11.11", "10.11.12", "the document")
    with pytest.raises(bump.BumpError) as refusal:
        bump.apply_all((edit,))
    assert "matched 2 lines" in str(refusal.value)


def test_the_image_digest_is_required_because_a_new_version_is_a_new_image() -> None:
    """ADR-0007 pins by digest and never by tag, so a bump with no digest is not a bump.

    Refused at the boundary rather than at step 4, because discovering it at step 4 means the
    whole procedure ran — a differential, twenty named comparisons and fifty-three probes — for a
    write that was never going to happen.
    """
    ctx = bump.Context(args=namespace(image=None), read_version=lambda url, timeout=30: "10.11.12")
    with pytest.raises(bump.BumpError) as refusal:
        bump.prepare(ctx.args, ctx)
    assert "--image" in str(refusal.value)

    ctx = bump.Context(
        args=namespace(image="jellyfin/jellyfin:10.11.12"),
        read_version=lambda url, timeout=30: "10.11.12",
    )
    with pytest.raises(bump.BumpError):
        bump.prepare(ctx.args, ctx)


def test_a_bump_that_changed_the_server_and_names_no_atrium_refuses_before_step_one() -> None:
    """Step 2 is mandatory for this move and it takes two servers. Refuse now, not in an hour."""
    ctx = bump.Context(args=namespace(atrium=None), read_version=lambda url, timeout=30: "10.11.12")
    with pytest.raises(bump.BumpError) as refusal:
        bump.prepare(ctx.args, ctx)
    assert "--atrium" in str(refusal.value)


def test_the_behavioural_row_is_what_the_move_is_measured_against() -> None:
    """The contract row moves on a document-only bump; the behavioural one does not.

    Reading the wrong row would make every move look like a server change — safe, and it would
    make the distinction conformance.md draws a decoration.
    """
    text = bump.REFERENCE_TARGET.read_text(encoding="utf-8")
    assert bump.pinned_behavioural_version(text) == "10.11.11"
    assert bump.pinned_behavioural_version("| API contract | Jellyfin `9.9.9` |") is None


def test_step_one_validates_a_candidate_surface_and_never_the_pinned_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The finding that shaped step 1: the validator cannot run with the old pin in place.

    `extract_v1_surface.py` compares the document's own `info.version` with `surface.yaml`'s pin
    and errors when they differ — measured on 2026-09-02, exit 1, the mismatch being the only
    error while every path check passed. So step 1 on a real bump would fail at step 1, always,
    before reporting the disappeared paths it exists to report. The way out keeps step 4 the only
    writer: the surface is copied with the pin moved and the **copy** is validated.
    """
    runner = _all_pass(monkeypatch, tmp_path)
    ctx = context(runner)
    ctx.args.dry_run = True
    result = bump.step_one_the_document(ctx)
    assert result.outcome is bump.Outcome.PASSED

    validation = next(call for call in runner.calls if Path(call[1]).stem == "extract_v1_surface")
    surface = Path(validation[validation.index("--surface") + 1])
    assert surface != bump.SURFACE, "step 1 validated the pinned surface, which cannot pass"
    assert 'jellyfin_openapi_version: "10.11.12"' in surface.read_text(encoding="utf-8")
    assert bump.SURFACE.read_text(encoding="utf-8").count("10.11.12") == 0


def test_a_disappeared_path_is_named_as_a_breaking_change(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Step 1's real product, and it arrives as an ordinary validator error to everyone else."""
    runner = _all_pass(
        monkeypatch,
        tmp_path,
        extract_v1_surface=(1, "error: GET /System/Info/Public: path not present in the pinned"),
    )
    ctx = context(runner)
    result = bump.step_one_the_document(ctx)
    assert result.outcome is bump.Outcome.CHANGED
    assert "GET /System/Info/Public" in result.summary
    assert any("breaking change" in line for line in result.detail)


def test_a_document_that_does_not_say_what_the_bump_claims_stops_the_procedure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`--to` names a version and the server has to agree, or the pin would name a fiction."""
    monkeypatch.setattr(bump, "OUTPUT", tmp_path / "reference")
    document = tmp_path / "reference" / "openapi-10.11.12.json"

    def runner(argv: Sequence[str]) -> Any:
        document.parent.mkdir(parents=True, exist_ok=True)
        document.write_text('{"info": {"version": "10.11.13"}}', encoding="utf-8")
        return bump.Completed(argv=tuple(argv), returncode=0)

    ctx = bump.Context(args=namespace(), runner=runner, pinned="10.11.11")
    result = bump.step_one_the_document(ctx)
    assert result.outcome is bump.Outcome.CHANGED
    assert "10.11.13" in result.summary


def test_step_three_runs_every_probe_before_it_reports(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The step is the unit of the procedure, not the probe.

    The probes are independent of each other and nothing downstream consumes one's output, so
    stopping at the first contradiction would cost a day per finding and buy nothing; what stops
    is the **procedure**, and step 4 does not run. A bump wants every contradiction at once.
    """
    scripts = tuple(
        bump.ProbeScript(
            path=tmp_path / f"probe_{name}.py", writes=False, makes_its_own_server=False
        )
        for name in ("one", "two", "three")
    )
    for script in scripts:
        script.path.write_text("# stand-in\n", encoding="utf-8")
    monkeypatch.setattr(bump, "probe_scripts", lambda *_: scripts)

    runner = Runner(probe_two=(1, "  CONTRADICTION"))
    ctx = context(runner)
    result = bump.step_three_the_probes(ctx)

    assert result.outcome is bump.Outcome.CHANGED
    assert runner.ran("probe_three"), (
        "probe_two contradicted the documentation and probe_three never ran. The probes are "
        "independent: what a failure stops is the procedure, not the sweep."
    )
    assert "1 of 3 probes did not pass" in result.summary


def test_a_leak_is_reported_as_a_leak_and_not_as_a_contradiction(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Exit `3` means something this run created is still on the server (T13).

    It is a failure of the bump — pinning a version having left an account behind on the server
    just pinned is not a completed procedure — and it is not a difference anybody can triage.
    """
    script = bump.ProbeScript(
        path=tmp_path / "probe_leaks.py", writes=True, makes_its_own_server=False
    )
    script.path.write_text("# stand-in\n", encoding="utf-8")
    monkeypatch.setattr(bump, "probe_scripts", lambda *_: (script,))
    ctx = context(Runner(probe_leaks=(3, "cleanup: 1 object(s) this run created are still there")))
    result = bump.step_three_the_probes(ctx)
    assert result.outcome is bump.Outcome.LEAKED
    assert not result.carries_on


def test_only_passed_and_skipped_let_the_procedure_reach_the_next_step() -> None:
    """The one-line rule the whole sequencer turns on, asserted over every outcome there is."""
    carry_on = {outcome for outcome in bump.Outcome if outcome.carries_on}
    assert carry_on == {bump.Outcome.PASSED, bump.Outcome.SKIPPED}
