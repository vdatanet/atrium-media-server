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

The probe-convention half of this file — every `tools/probe_*.py` reaching the shared entry point,
and the cleanup contract — is 010 T13's and is not here yet.
"""

from __future__ import annotations

import re
from pathlib import Path

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
