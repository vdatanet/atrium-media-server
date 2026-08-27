# SPDX-License-Identifier: GPL-3.0-or-later
"""The culture table, and the measurement it came from.

`GET /Localization/Cultures` reaches **L2**: the response is byte-compared against a checked-in
golden in `tests/conformance/test_golden.py`. What this suite holds is the table itself - that it
is the list the reference actually returns rather than the one plan section 6.9 assumed, and that
the generator which produced it is deterministic.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from atrium.metadata.cultures import CULTURES, Culture

REPO = Path(__file__).resolve().parents[2]
GENERATOR = REPO / "tools" / "generate_cultures.py"
TABLE = REPO / "src" / "atrium" / "metadata" / "cultures.py"

#: Measured on a live server `[probe: tools/generate_cultures.py, Jellyfin 10.11.11, 2026-08-27]`.
#: The registry plan section 6.9 named has 508 rows; this is what the reference returns.
MEASURED_COUNT = 192


def test_the_table_is_the_measured_list_rather_than_the_registry() -> None:
    """**The finding this task exists for.** Plan section 6.9 said the Library of Congress ISO
    639-2 registry, which has 508 rows. The reference returns 192 - only the languages that carry
    a two-letter code - plus eight rows the registry does not contain at all."""
    assert len(CULTURES) == MEASURED_COUNT


def test_every_culture_carries_a_two_letter_code() -> None:
    """The filter that turns 508 into 192, stated as a property of the table."""
    assert all(one.two_letter for one in CULTURES)


def test_the_terminological_code_comes_first() -> None:
    """French is `["fra", "fre"]`, not `["fre", "fra"]`.

    The registry's own file lists the bibliographic code first; the reference swaps them. A client
    reads the first entry, so getting this backwards labels French audio as `fre` where every
    other server says `fra`.
    """
    french = next(one for one in CULTURES if one.two_letter == "fr")
    assert french.three_letters == ("fra", "fre")
    assert french.three_letter == "fra"

    german = next(one for one in CULTURES if one.two_letter == "de")
    assert german.three_letters == ("deu", "ger")


def test_a_language_with_one_code_carries_a_list_of_one() -> None:
    """Not a bare string. The property is an array in `[spec: CultureDto]` and a client that
    indexed into a string would read one character."""
    english = next(one for one in CULTURES if one.two_letter == "en")
    assert english.three_letters == ("eng",)


def test_twenty_four_languages_carry_both_codes() -> None:
    assert sum(1 for one in CULTURES if len(one.three_letters) > 1) == 24


@pytest.mark.parametrize("tag", ["zh-hk", "zh-cn", "zh-tw", "fr-ca", "pt-br", "pt-pt", "es-419"])
def test_the_regional_rows_the_registry_does_not_have(tag: str) -> None:
    """Seven rows whose "two-letter code" is a tag, and one more (`ze`) that is two letters and
    not ISO. **No amount of filtering the registry produces these**, which is what settled the
    question of where the table comes from."""
    row = next((one for one in CULTURES if one.two_letter == tag), None)
    assert row is not None, f"{tag} is missing; the table was regenerated from the wrong source"
    assert row.name == tag, "a tagged row's Name is the tag; its DisplayName is the friendly one"
    assert row.display_name != tag


def test_the_bilingual_chinese_row_is_there_too() -> None:
    row = next((one for one in CULTURES if one.two_letter == "ze"), None)
    assert row is not None
    assert row.three_letters == ("zho", "chi")


def test_names_keep_the_registrys_own_punctuation() -> None:
    """`Dutch; Flemish` is one culture with one name, not two cultures and not a list. Splitting
    it would invent a language."""
    dutch = next(one for one in CULTURES if one.two_letter == "nl")
    assert dutch.name == "Dutch; Flemish"
    assert dutch.display_name == "Dutch; Flemish"


def test_the_table_is_frozen() -> None:
    """It is data. A caller that could edit it could change what one request returns for every
    later one."""
    assert isinstance(CULTURES, tuple)
    with pytest.raises(AttributeError):
        CULTURES[0].name = "Something Else"  # type: ignore[misc]


def test_a_culture_is_the_five_properties_the_spec_declares() -> None:
    fields = set(Culture.__dataclass_fields__)
    assert fields == {
        "name",
        "display_name",
        "two_letter",
        "three_letter",
        "three_letters",
    }


# ----------------------------------------------------------------------------------------------
# The generator
# ----------------------------------------------------------------------------------------------


def test_the_generator_runs_on_the_python_the_tools_job_uses() -> None:
    """`tools/` carries a 3.9 floor and the CI job holds it there, so this file may not use a
    3.10+ spelling. Compiling it is the same check that job makes."""
    result = subprocess.run(  # noqa: S603 - the interpreter running this test, and one file
        [sys.executable, "-m", "py_compile", str(GENERATOR)],
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode()


def test_the_generator_starts_without_a_server() -> None:
    """The `tools` CI job runs every script with `--help`. One that needed a server to print its
    own usage would fail there rather than here."""
    result = subprocess.run(  # noqa: S603 - the interpreter running this test, and one file
        [sys.executable, str(GENERATOR), "--help"], capture_output=True, check=False
    )
    assert result.returncode == 0
    assert b"--from-file" in result.stdout


def test_running_the_generator_twice_produces_identical_bytes(tmp_path: Path) -> None:
    """Determinism, without a server: the saved-response path takes the table this build already
    has and regenerates it, which must reproduce the committed file exactly.

    A generator that reordered its own output would turn every regeneration into a diff nobody
    could review, which is how a generated file stops being reviewed at all.
    """
    import json

    saved = tmp_path / "cultures.json"
    saved.write_text(
        json.dumps(
            [
                {
                    "Name": one.name,
                    "DisplayName": one.display_name,
                    "TwoLetterISOLanguageName": one.two_letter,
                    "ThreeLetterISOLanguageName": one.three_letter,
                    "ThreeLetterISOLanguageNames": list(one.three_letters),
                }
                for one in CULTURES
            ]
        ),
        encoding="utf-8",
    )

    before = TABLE.read_bytes()
    try:
        first = subprocess.run(  # noqa: S603 - the interpreter running this test
            [sys.executable, str(GENERATOR), "--from-file", str(saved)],
            capture_output=True,
            check=False,
        )
        assert first.returncode == 0, first.stderr.decode()
        once = TABLE.read_bytes()

        second = subprocess.run(  # noqa: S603 - the interpreter running this test
            [sys.executable, str(GENERATOR), "--from-file", str(saved)],
            capture_output=True,
            check=False,
        )
        assert second.returncode == 0
        assert TABLE.read_bytes() == once, "two runs produced different bytes"
        assert b"unchanged" in second.stdout, "the second run should report no change"
    finally:
        TABLE.write_bytes(before)


def test_the_generator_refuses_a_response_of_the_wrong_shape(tmp_path: Path) -> None:
    """A committed table is only as trustworthy as the check in front of it. A server that started
    answering something else must not quietly become `cultures.py`."""
    saved = tmp_path / "wrong.json"
    saved.write_text('[{"Name": "French"}]', encoding="utf-8")
    before = TABLE.read_bytes()
    result = subprocess.run(  # noqa: S603 - the interpreter running this test
        [sys.executable, str(GENERATOR), "--from-file", str(saved)],
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert TABLE.read_bytes() == before, "the table was rewritten from a response it refused"


def test_the_generator_has_a_row_in_the_tools_table() -> None:
    """Every script in `tools/` is held by that table; this one had no row when the tasks gate
    reviewed the list, which is how it came to be in T15's changes."""
    readme = (REPO / "tools" / "README.md").read_text(encoding="utf-8")
    assert "generate_cultures.py" in readme
