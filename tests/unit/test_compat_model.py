# SPDX-License-Identifier: GPL-3.0-or-later
"""The base model: PascalCase out, lenient in."""

from __future__ import annotations

import json

from atrium.compat.model import AtriumModel


class Sample(AtriumModel):
    local_address: str
    is_hd: bool
    id: str


def test_serialises_in_pascal_case() -> None:
    body = json.loads(Sample(local_address="http://host", is_hd=True, id="abc").model_dump_json())
    assert list(body) == ["LocalAddress", "IsHD", "Id"]


def test_serialises_without_being_asked() -> None:
    """`model_dump()` is correct by default, not only when the caller remembers `by_alias=True`.

    The one place someone forgets is the one place a client sees snake_case.
    """
    assert set(Sample(local_address="a", is_hd=False, id="b").model_dump()) == {
        "LocalAddress",
        "IsHD",
        "Id",
    }


def test_accepts_the_wire_spelling() -> None:
    assert Sample(LocalAddress="a", IsHD=True, Id="b").local_address == "a"


def test_accepts_the_python_spelling() -> None:
    assert Sample(local_address="a", is_hd=True, id="b").local_address == "a"


def test_accepts_any_casing() -> None:
    """The reference is an ASP.NET Core application and its JSON binder is case-insensitive.

    A client posting `{"username": ...}` where the property is declared `Username` is served by
    the reference, so it has to be served here too.
    """
    parsed = Sample.model_validate({"localaddress": "a", "ISHD": True, "iD": "b"})
    assert (parsed.local_address, parsed.is_hd, parsed.id) == ("a", True, "b")


def test_ignores_unknown_properties() -> None:
    parsed = Sample.model_validate(
        {"LocalAddress": "a", "IsHD": False, "Id": "b", "FromANewerServer": 1}
    )
    assert parsed.local_address == "a"
    assert "FromANewerServer" not in parsed.model_dump()


def test_non_dict_input_passes_through() -> None:
    """The case-insensitive remap must not disturb validation of anything that is not a mapping."""
    assert Sample.model_validate(Sample(local_address="a", is_hd=True, id="b")).id == "b"
