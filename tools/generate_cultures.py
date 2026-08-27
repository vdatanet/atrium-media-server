#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Regenerate `src/atrium/metadata/cultures.py` from a measurement of the reference.

`GET /Localization/Cultures` is static data, so Atrium ships a table rather than computing one -
and the question this script exists to answer is *which* table.

**The plan said the Library of Congress ISO 639-2 registry. The measurement says otherwise.**
Measured against a live server on 2026-08-27, the reference returns **192** rows where that
registry has 508, and the difference is not arbitrary:

* it keeps **only the languages that have a two-letter code**, which is the 192;
* it puts the **terminological** three-letter code first and the bibliographic one second, where
  the registry's own file lists them the other way round - so French is `["fra", "fre"]`, not
  `["fre", "fra"]`;
* and it adds **eight rows the registry does not have at all** - regional Chinese, Portuguese,
  French and Spanish, plus a bilingual Chinese entry - whose two-letter "codes" are tags like
  `pt-br`.

The last of those settles it. A table built from the registry would be missing eight rows a
client can ask for, and no amount of filtering produces them. So the **source is the reference
itself**, read through its own public API exactly as every probe in this directory reads one -
which is a stronger provenance than a third-party file, and makes the golden byte-compare in
`tests/conformance/` mean something.

(The registry was tried first. `loc.gov` answers a scripted request with a bot challenge, which is
a second reason this route is the right one rather than a compromise.)

Run it against a server, or against a saved response:

    python3 tools/generate_cultures.py
    python3 tools/generate_cultures.py --from-file cultures.json

Standard library only, and it runs on the 3.9 floor the `tools` CI job holds this directory to.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _probe

#: Where the generated module goes.
TARGET = Path(__file__).resolve().parents[1] / "src" / "atrium" / "metadata" / "cultures.py"

#: The five properties `[spec: CultureDto]` declares, in the order the model lists them.
FIELDS = (
    "Name",
    "DisplayName",
    "TwoLetterISOLanguageName",
    "ThreeLetterISOLanguageName",
    "ThreeLetterISOLanguageNames",
)


def rows_from(payload: Any) -> list[dict[str, Any]]:
    """The response, checked hard enough that a wrong one cannot become a committed table."""
    if not isinstance(payload, list) or not payload:
        raise _probe.ProbeError("GET /Localization/Cultures returned no list of cultures")
    rows = []
    for entry in payload:
        if not isinstance(entry, dict):
            raise _probe.ProbeError("a culture entry is not an object")
        missing = [name for name in FIELDS if name not in entry]
        if missing:
            raise _probe.ProbeError(
                f"a culture entry is missing {missing}; the response shape has changed "
                f"and metadata/cultures.py should not be regenerated from it"
            )
        rows.append(entry)
    return rows


def sanity(rows: list[dict[str, Any]]) -> list[str]:
    """What the measurement said, printed so a regeneration is a decision rather than a diff."""
    with_both = [one for one in rows if len(one["ThreeLetterISOLanguageNames"]) > 1]
    tagged = [one for one in rows if "-" in one["TwoLetterISOLanguageName"]]
    return [
        f"{len(rows)} cultures",
        f"{len(with_both)} carry two three-letter codes "
        f"(terminological first, bibliographic second)",
        "{} carry a regional tag rather than a two-letter code: {}".format(
            len(tagged), ", ".join(sorted(one["TwoLetterISOLanguageName"] for one in tagged))
        ),
        f"{sum(1 for one in rows if not one['TwoLetterISOLanguageName'])} "
        f"have no two-letter code at all",
    ]


def render(rows: list[dict[str, Any]], source: str, measured: str) -> str:
    """The module, as text. Deterministic: the same rows produce the same bytes."""
    entries = []
    for row in rows:
        names = ", ".join(_literal(one) for one in row["ThreeLetterISOLanguageNames"])
        entries.append(
            "    Culture(\n"
            "        name={},\n"
            "        display_name={},\n"
            "        two_letter={},\n"
            "        three_letter={},\n"
            "        three_letters=({}{}),\n"
            "    ),".format(
                _literal(row["Name"]),
                _literal(row["DisplayName"]),
                _literal(row["TwoLetterISOLanguageName"]),
                _literal(row["ThreeLetterISOLanguageName"]),
                names,
                "," if len(row["ThreeLetterISOLanguageNames"]) == 1 else "",
            )
        )

    return HEADER.format(
        source=source, measured=measured, count=len(rows), entries="\n".join(entries)
    )


def _literal(text: str) -> str:
    """A Python string literal that round-trips, with no surprises about quoting."""
    return json.dumps(text, ensure_ascii=False)


HEADER = '''# SPDX-License-Identifier: GPL-3.0-or-later
"""The culture table `GET /Localization/Cultures` serves.

**Generated. Do not edit by hand** - run `tools/generate_cultures.py` and commit the result.

Source: {source}
Measured: {measured}
Rows: {count}

Static data, so it is a table rather than a computation. The list is **not** the Library of
Congress ISO 639-2 registry, which has 508 rows: the reference keeps only the languages that carry
a two-letter code, lists the *terminological* three-letter code before the bibliographic one, and
adds eight rows of its own for regional variants whose "two-letter code" is a tag like `pt-br`.
See `tools/generate_cultures.py` for the whole of that reasoning.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Culture:
    """One language, as `[spec: CultureDto]` declares it.

    `three_letters` carries both codes when a language has two, terminological first. That order is
    the reference's and it is what a client reads when it labels an audio track: a file tagged
    `ger` and a file tagged `deu` are both German, and a client that only knew one of them would
    label one of the two as unknown.
    """

    name: str
    display_name: str
    two_letter: str
    three_letter: str
    three_letters: tuple[str, ...]


CULTURES = (
{entries}
)

__all__ = ["CULTURES", "Culture"]
'''


def run(server: Any) -> Any:
    """A `Probe`, so this reports and exits like every other script here.

    It **generates** rather than only observing, which is the one way it differs - and it still
    ends by saying what it saw and whether that contradicts what the documentation claims, so a
    server upgrade that changed the list says so instead of silently rewriting a committed table.
    """
    probe = _probe.Probe(
        script="generate_cultures.py",
        question="What does GET /Localization/Cultures return, and what should the table be?",
        document="specs/004-metadata-resolution/plan.md",
        section="6.9",
        expectation="192 cultures, terminological code first, eight regional rows",
    )
    rows = rows_from(server.get("/Localization/Cultures"))
    changed, lines = _write(rows, f"GET /Localization/Cultures on Jellyfin {server.version}")
    for line in lines:
        label, _, value = line.partition(" ")
        probe.observe(label if value else line, value)
    probe.conclude(
        f"{len(rows)} cultures written to {TARGET.name}",
        matches_documentation=len(rows) == EXPECTED_ROWS,
    )
    if changed:
        probe.note("The committed table changed. Read the diff before committing it.")
    return probe


#: What the measurement of 2026-08-27 found. A different number is not an error - it is a finding,
#: and the probe reports it as one rather than quietly rewriting the table to match.
EXPECTED_ROWS = 192


def _write(rows: list[dict[str, Any]], source: str) -> tuple[bool, list[str]]:
    measured = datetime.now(timezone.utc).date().isoformat()
    text = render(rows, source, measured)
    before = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
    TARGET.write_text(text, encoding="utf-8")

    lines = sanity(rows)
    lines.append(f"wrote {TARGET}")
    return before != text, lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--from-file",
        type=Path,
        default=None,
        help="A saved GET /Localization/Cultures response, instead of asking a server",
    )
    known, rest = parser.parse_known_args()
    if known.from_file is not None:
        rows = rows_from(json.loads(known.from_file.read_text(encoding="utf-8")))
        changed, lines = _write(rows, f"saved response {known.from_file.name}")
        for line in lines:
            print(line)
        print("changed" if changed else "unchanged")
        return 0

    sys.argv = [sys.argv[0], *rest]
    return _probe.main(run, description=__doc__.splitlines()[0])


if __name__ == "__main__":
    raise SystemExit(main())
