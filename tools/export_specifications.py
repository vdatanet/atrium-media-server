#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Export the language-neutral half of this repository into a virgin project.

The premise is [specs/README.md](../specs/README.md)'s own test of a good specification -- *two
competent engineers could implement it in two different languages and their servers would be
indistinguishable to a client* -- taken literally: copy out what a second implementation is
entitled to inherit, withhold what it has to earn, and say in writing which is which.

**What separates an export from a copy is the refusal.** `spec.md` is WHAT and WHY and travels;
`plan.md` and `tasks.md` are HOW and STEPS and do not, because a second implementation that starts
from the first one's plan is a transliteration and measures nothing. The compatibility documents
travel whole -- they are measurements of the *reference*, not decisions of this implementation, and
re-deriving them would be paying twice for the same reading. Four of this repository's eight
architecture decisions travel; the stack, the store, the password hashing and this export's own
record are decisions the receiving project takes for itself.

**Every tracked path is classified or the export fails.** A file that is neither exported nor
withheld exits `1` and names itself, so a document added next month cannot be silently left behind
or silently shipped. That is the same discipline the allowlist has in
[conformance.md](../docs/compatibility/conformance.md): an undeclared thing is a failure, never a
default.

**What it will not do is edit.** The exported bytes are the bytes at the ref, and the two things
that are wrong with them in their new home are reported rather than fixed:

* **Leaks** -- prose naming a technology, and pointers into `src/` and `tests/`. Naming something
  under `tools/` is not a leak, in a citation or bare: those scripts measure the reference or judge
  two servers over HTTP, they stay in this repository, and the receiving project points them at its
  own address rather than rewriting them. Everything else is a sentence somebody has to read.
* **Frontmatter that is about the exporting project.** A spec exported with `status: Implemented`
  is asserting something true here and false there. The receiving project resets it; this command
  lists which files, and never touches one.

Both go into a `PROVENANCE.md` in the destination together with the resolved commit, the export
digest, and the withheld set with its reasons -- so a later claim that two implementations agree
names the snapshot of the specifications it agrees on. `--strict` turns the leak census into a
failure, which is what CI would want and what a first run will not survive.

**Choosing the ref is choosing the experiment.** `--from HEAD` exports the specifications as they
stand, amendments and all, and asks whether a mature specification is complete enough for another
language to arrive at the same place. `--from <the commit that accepted them>` exports them as
written before any code existed, and asks the harder question: whether the loop finds the same
things again. They are different experiments and they do not belong in the same destination.

Standard library only, on the Python 3.9 floor, like everything under tools/ (010 plan D-2).

Usage:
    python3 tools/export_specifications.py --help
    python3 tools/export_specifications.py --to ../atrium-go --dry-run
    python3 tools/export_specifications.py --to ../atrium-go --from HEAD
    python3 tools/export_specifications.py --to ../atrium-spec-as-accepted --from df70b87
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import posixpath
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

REPOSITORY = Path(__file__).resolve().parent.parent

# Ordered; the first pattern a path matches decides it. `fnmatch` lets `*` cross a separator, so
# the specific rules come before the sweeping ones and every prefix rule is deliberate.
Rule = Tuple[bool, str, str]

MANIFEST: Tuple[Rule, ...] = (
    (
        True,
        "specs/README.md",
        "The method: the loop, the three artefacts, and what makes them different",
    ),
    (True, "specs/templates/*", "The artefact templates the method is written against"),
    (
        True,
        "specs/*/spec.md",
        "WHAT and WHY -- the artefact a second language is entitled to inherit",
    ),
    (True, "specs/*/notes/*", "Readings a specification cites"),
    (
        False,
        "specs/*/plan.md",
        "HOW -- inheriting it makes the second implementation a transliteration",
    ),
    (
        False,
        "specs/*/tasks.md",
        "STEPS -- they belong to a plan the receiving project has not written",
    ),
    (
        True,
        "docs/compatibility/*",
        "Measurements of the reference, not decisions of this implementation",
    ),
    (True, "docs/constitution.md", "The principles the method rests on"),
    (True, "docs/glossary.md", "Jellyfin's vocabulary, which both implementations speak"),
    (True, "docs/decisions/README.md", "How a decision is recorded"),
    (
        True,
        "docs/decisions/0001-*",
        "Implement the Jellyfin API rather than a new one -- the premise, not the stack",
    ),
    (
        True,
        "docs/decisions/0004-*",
        "The pinned reference version, which both implementations must share",
    ),
    (True, "docs/decisions/0005-*", "The licence the exported documents travel under"),
    (
        True,
        "docs/decisions/0007-*",
        "The single-use reference instance, which is a method and not a runtime",
    ),
    (
        False,
        "docs/decisions/0008-*",
        "This export's own record: a decision about the exporting project",
    ),
    (
        False,
        "docs/decisions/*",
        "Stack, store and password hashing: decisions the receiving project takes for itself",
    ),
    (False, "docs/architecture.md", "This implementation's shape"),
    (False, "docs/roadmap.md", "This implementation's order of work"),
    (False, "docs/README.md", "An index of documents this export withholds"),
    (False, "docs/audits/*", "Audits of this implementation"),
    (True, "LICENSE", "GPL-3.0-or-later travels with the documents"),
    (False, "AGENTS.md", "Working instructions naming this repository's layout and commands"),
    (False, "README.md", "This implementation's front page"),
    (False, "src/*", "The implementation itself"),
    (False, "tests/*", "Tests written against the implementation"),
    (False, "tools/*", "Probes and harness stay here and are pointed at the new server over HTTP"),
    (False, "pyproject.toml", "Build configuration of the exporting stack"),
    (False, "uv.lock", "Build configuration of the exporting stack"),
    (False, "alembic.ini", "Build configuration of the exporting stack"),
    (False, ".env.example", "Credentials and endpoints of this installation"),
    (False, ".gitignore", "Ignores paths the receiving project does not have"),
    (False, ".github/*", "CI wired to the exporting stack"),
    (False, ".claude/*", "Agent configuration pointing at this repository"),
)

# Provenance forms are quoted paths into Jellyfin or into this repository's probes, and the probes
# are reused rather than rewritten (010 section 3.5). They are masked before the scan, not flagged.
PROVENANCE = re.compile(r"\[(?:probe|prior-probe|source|spec):\s[^\]]*\]")
# Everything under tools/ measures the reference or judges over HTTP; none of it is the server.
# The receiving project points the same scripts at its own address, so naming one -- in a citation
# or bare in an open-question table -- is reuse and not a leak. `src/` and `tests/` are the halves
# that stayed behind.
REUSED = re.compile(r"\btools/[A-Za-z0-9_./-]+\.py\b")
TECHNOLOGY = re.compile(
    r"\b(?:python|fastapi|sqlalchemy|sqlite|aiosqlite|pytest|uvicorn|starlette|pydantic"
    r"|alembic|ruff|mypy|httpx|asgi)\b",
    re.IGNORECASE,
)
IMPLEMENTATION_PATH = re.compile(
    r"(?:\b(?:src|tests)/[A-Za-z0-9_./-]+)|(?:\b[A-Za-z0-9_./-]+\.py\b)"
    r"|(?:\b(?:pyproject\.toml|uv\.lock|alembic\.ini)\b)"
)
LINK = re.compile(r"\]\((?P<target>[^)#\s]+)(?:#[^)\s]*)?\)")
STATUS = re.compile(r"^status:\s*(?P<value>.+)$", re.MULTILINE)

TEXT_SUFFIXES = (".md", ".yaml", ".yml", ".json")


class ExportError(Exception):
    """The export could not look: no git, no such ref, a destination it may not write."""


#: `git`, resolved on first use. Not at import, so `--help` reaches nothing (tools/README.md).
_GIT: Optional[str] = None


@dataclass
class Leak:
    path: str
    line: int
    kind: str
    text: str


@dataclass
class Census:
    exported: List[Tuple[str, str]] = field(default_factory=list)
    withheld: List[Tuple[str, str]] = field(default_factory=list)
    unclassified: List[str] = field(default_factory=list)
    leaks: List[Leak] = field(default_factory=list)
    dangling: Dict[str, List[str]] = field(default_factory=dict)
    statuses: List[Tuple[str, str]] = field(default_factory=list)


def executable() -> str:
    """`git`, resolved once, so a machine without one says so rather than raising an OSError.

    Resolved rather than named on the command line for the reason `media/probe.py` resolves
    `ffprobe`: an absolute executable with a fixed argument list is the shape that never re-reads
    its arguments through a shell.
    """
    global _GIT
    if _GIT is None:
        found = shutil.which("git")
        if found is None:
            raise ExportError("git is not on PATH, and every byte this exports is read through it")
        _GIT = found
    return _GIT


def git(*arguments: str) -> str:
    finished = subprocess.run(  # noqa: S603 - the arguments are this module's own
        [executable(), *arguments], cwd=str(REPOSITORY), capture_output=True, text=True
    )
    if finished.returncode != 0:
        raise ExportError(f"git {' '.join(arguments)}: {finished.stderr.strip()}")
    return finished.stdout


def git_bytes(*arguments: str) -> bytes:
    finished = subprocess.run(  # noqa: S603 - the arguments are this module's own
        [executable(), *arguments], cwd=str(REPOSITORY), capture_output=True
    )
    if finished.returncode != 0:
        raise ExportError(f"git {' '.join(arguments)}: {finished.stderr.decode().strip()}")
    return finished.stdout


def classify(path: str) -> Optional[Tuple[bool, str]]:
    for exported, pattern, reason in MANIFEST:
        if fnmatch.fnmatch(path, pattern):
            return exported, reason
    return None


def take(ref: str) -> Census:
    """Classify every tracked path at `ref`. An unclassified one is the failure this exists for."""
    census = Census()
    for path in sorted(git("ls-tree", "-r", "--name-only", ref).split("\n")):
        if not path:
            continue
        decided = classify(path)
        if decided is None:
            census.unclassified.append(path)
        elif decided[0]:
            census.exported.append((path, decided[1]))
        else:
            census.withheld.append((path, decided[1]))
    return census


def scan(path: str, body: bytes, census: Census, exported: Set[str]) -> None:
    """Read the exported bytes for the two things that are true here and wrong in the new home."""
    if not path.endswith(TEXT_SUFFIXES):
        return
    text = body.decode("utf-8", errors="replace")

    # A citation wraps across lines as often as not, so the mask is taken over the whole document
    # and blanks the span in place: masking line by line reports a probe as a leak on every
    # citation the prose happened to break.
    def blank(found: re.Match) -> str:
        """Replace a span with spaces, keeping its newlines, so line numbers do not move."""
        return re.sub(r"[^\n]", " ", found.group(0))

    masked = REUSED.sub(blank, PROVENANCE.sub(blank, text))
    # `strict=` would say what the two have in common - the mask preserves every newline, so they
    # are the same length by construction - and it is Python 3.10, above this file's floor.
    pairs = zip(text.split("\n"), masked.split("\n"))  # noqa: B905
    for number, (line, cleared) in enumerate(pairs, start=1):
        for pattern, kind in ((IMPLEMENTATION_PATH, "path"), (TECHNOLOGY, "technology")):
            if pattern.search(cleared):
                census.leaks.append(Leak(path, number, kind, line.strip()[:160]))
                break

    for found in LINK.finditer(text):
        target = found.group("target")
        if target.startswith(("http://", "https://", "mailto:")):
            continue
        resolved = posixpath.normpath(posixpath.join(posixpath.dirname(path), target))
        if resolved not in exported:
            census.dangling.setdefault(resolved, []).append(path)

    if path.endswith("spec.md"):
        state = STATUS.search(text)
        if state is not None and state.group("value").strip() != "Draft":
            census.statuses.append((path, state.group("value").strip()))


def destination_for(argument: str) -> Path:
    where = Path(argument).expanduser().resolve()
    if where.exists():
        if not where.is_dir():
            raise ExportError(f"{argument} is not a directory")
        if any(where.iterdir()):
            raise ExportError(
                f"{argument} is not empty -- an export goes into a virgin project, and refusing "
                "here is what keeps one export from being read as another"
            )
    return where


def provenance(census: Census, ref: str, commit: str, digest: str, dirty: Sequence[str]) -> str:
    when = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    origin = git("config", "--get", "remote.origin.url").strip() or "not recorded"
    withheld_reasons: Dict[str, int] = {}
    for _path, reason in census.withheld:
        withheld_reasons[reason] = withheld_reasons.get(reason, 0) + 1

    lines = [
        "# Provenance",
        "",
        "These documents were exported from another repository. They are specifications and",
        "measurements; no implementation came with them, deliberately.",
        "",
        f"- source: {origin}",
        f"- ref: `{ref}`",
        f"- commit: `{commit}`",
        f"- exported: {when}",
        f"- export digest: `sha256:{digest}`",
        f"- files: {len(census.exported)} exported, {len(census.withheld)} withheld",
        "",
        "Licence: GPL-3.0-or-later, as it was at the source. `LICENSE` travelled with them.",
        "",
    ]

    if dirty:
        lines += [
            "**The exporting worktree had uncommitted changes to exported paths.** The bytes here",
            "are the committed ones at the ref above, so those changes are *not* in this export:",
            "",
            *[f"- `{path}`" for path in dirty],
            "",
        ]

    lines += [
        "## What was withheld, and why",
        "",
        "| Reason | Files |",
        "|---|---|",
        *[f"| {reason} | {count} |" for reason, count in sorted(withheld_reasons.items())],
        "",
        "## What the receiving project must decide first",
        "",
    ]

    if census.statuses:
        lines += [
            "These specifications carry a `status:` that is a statement about the *exporting*",
            "project. Nothing here is implemented until this project implements it, and this",
            "command does not edit an exported byte:",
            "",
            "| File | `status:` at the source |",
            "|---|---|",
            *[f"| `{path}` | {value} |" for path, value in sorted(census.statuses)],
            "",
        ]
    else:
        lines += ["Every exported specification is `Draft` at the source.", ""]

    lines += [
        "## Leaks",
        "",
        "Lines in the exported documents that name a technology, or point at a file that stayed",
        "behind. A probe citation is not among them: the probes measure the reference, they remain",
        "in the source repository, and this project points them at its own server rather than",
        f"rewriting them. **{len(census.leaks)} lines**, by file:",
        "",
    ]
    by_file: Dict[str, List[Leak]] = {}
    for leak in census.leaks:
        by_file.setdefault(leak.path, []).append(leak)
    lines += ["| File | Lines |", "|---|---|"]
    lines += [f"| `{path}` | {len(found)} |" for path, found in sorted(by_file.items())]
    lines += ["", "<details><summary>Every line</summary>", ""]
    lines += [f"- `{leak.path}:{leak.line}` ({leak.kind}) — {leak.text}" for leak in census.leaks]
    lines += ["", "</details>", "", "## Links with nothing to point at", ""]
    lines += [
        "Each was withheld above. A link is left as it was written: retargeting one is an edit to",
        "a specification, and that is this project's decision rather than the export's.",
        "",
        "| Target | Cited by |",
        "|---|---|",
    ]
    lines += [
        f"| `{target}` | {len(sorted(set(sources)))} file(s) |"
        for target, sources in sorted(census.dangling.items())
    ]
    lines.append("")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export the language-neutral specifications into a virgin project.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--to", required=True, help="Destination directory; must be empty or absent"
    )
    parser.add_argument(
        "--from",
        dest="ref",
        default="HEAD",
        help="Git ref to export from. HEAD exports the specifications as amended; the commit that "
        "accepted them exports what was written before any code existed",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail on the leak census as well as on an unclassified path",
    )
    parser.add_argument("--dry-run", action="store_true", help="Classify and report; write nothing")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        where = destination_for(args.to)
        commit = git("rev-parse", args.ref).strip()
        census = take(args.ref)
    except ExportError as failure:
        print(f"export_specifications.py: {failure}", file=sys.stderr)
        return 2

    if census.unclassified:
        print(
            "export_specifications.py: these tracked paths are neither exported nor withheld. "
            "Classify each in MANIFEST -- a document nobody decided about is the one failure this "
            "command exists to prevent:",
            file=sys.stderr,
        )
        for path in census.unclassified:
            print(f"  {path}", file=sys.stderr)
        return 1

    exported_paths = {path for path, _reason in census.exported}
    modified = set(git("status", "--porcelain", "--", ".").split("\n"))
    dirty = sorted(line[3:] for line in modified if len(line) > 3 and line[3:] in exported_paths)

    digest = hashlib.sha256()
    written: List[Tuple[str, bytes]] = []
    try:
        for path, _reason in census.exported:
            body = git_bytes("show", f"{args.ref}:{path}")
            digest.update(path.encode("utf-8"))
            digest.update(body)
            scan(path, body, census, exported_paths)
            written.append((path, body))
    except ExportError as failure:
        print(f"export_specifications.py: {failure}", file=sys.stderr)
        return 2

    report = provenance(census, args.ref, commit, digest.hexdigest(), dirty)

    if args.dry_run:
        print(f"--dry-run: nothing written to {args.to}")
    else:
        try:
            for path, body in written:
                target = where / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(body)
            (where / "PROVENANCE.md").write_text(report, encoding="utf-8")
        except OSError as failure:
            print(f"export_specifications.py: {failure}", file=sys.stderr)
            return 2

    print(
        f"export_specifications.py: {len(census.exported)} exported, "
        f"{len(census.withheld)} withheld, {len(census.leaks)} leak lines, "
        f"{len(census.dangling)} link targets left behind, from {args.ref} ({commit[:7]})"
    )
    if dirty:
        print(
            f"export_specifications.py: {len(dirty)} exported path(s) are modified in the "
            "worktree and the committed bytes were exported instead; PROVENANCE.md names them"
        )
    if not args.dry_run:
        print(f"export_specifications.py: provenance written to {where / 'PROVENANCE.md'}")
    if census.leaks and args.strict:
        print(
            "export_specifications.py: --strict, and the export carries "
            f"{len(census.leaks)} leak line(s)",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
