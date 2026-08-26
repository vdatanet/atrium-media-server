# SPDX-License-Identifier: GPL-3.0-or-later
"""Field name to wire name.

The reference serialises every JSON property in PascalCase, and for 988 of its 1043 property names
an alias generator produces the right answer. For 55 it does not, because acronyms stay uppercase:
`IsHD`, `IsAVC`, `TwoLetterISOLanguageName`.

The table below is not the guarantee. `tests/conformance/test_aliases.py` is: it checks every alias
this project produces against an index of the names the reference actually uses, so a missing entry
fails a test instead of reaching a client. Adding a field with an acronym in it and forgetting to
add it here is meant to be caught, not avoided by remembering.

See specs/001-server-identity-and-discovery/plan.md section 6.1.
"""

from __future__ import annotations

from typing import Final

from pydantic.alias_generators import to_pascal

#: Field names whose wire spelling a generator cannot produce. Every one of these was measured
#: against the pinned OpenAPI document, and the schema each belongs to is named so a reader can
#: check it. Sorted by field name.
IRREGULAR: Final[dict[str, str]] = {
    "is_avc": "IsAVC",  # MediaStream
    "is_hd": "IsHD",  # BaseItemDto
    "three_letter_iso_language_name": "ThreeLetterISOLanguageName",  # CultureDto
    "three_letter_iso_language_names": "ThreeLetterISOLanguageNames",  # CultureDto
    "two_letter_iso_language_name": "TwoLetterISOLanguageName",  # CultureDto
}


def atrium_alias(field_name: str) -> str:
    """Return the wire name for a Python field name."""
    return IRREGULAR.get(field_name, to_pascal(field_name))


__all__ = ["IRREGULAR", "atrium_alias"]
