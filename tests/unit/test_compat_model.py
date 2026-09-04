# SPDX-License-Identifier: GPL-3.0-or-later
"""The base model: PascalCase out, lenient in."""

from __future__ import annotations

import json
from enum import Enum

import pytest
from pydantic import ValidationError

from atrium.compat.model import AtriumModel, ordinals_of, wire_default, wire_ordinals


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


# ------------------------------------------------------------------------------------------------
# The vocabulary binder (012 T7)
# ------------------------------------------------------------------------------------------------


@wire_ordinals({0: "first", 1: "second", 3: "fourth"})
class Vocabulary(Enum):
    """A vocabulary with a gap in its numbers, which is the shape the reference really has.

    `ProfileConditionValue` skips 15, so its members past `RefFrames` all sit one above their
    position `[source: MediaBrowser.Model/Dlna/ProfileConditionValue.cs @ v10.11.11]`. A binder
    counting members would bind `2` and `3` to the wrong ones here, which is exactly what it does
    there.
    """

    FIRST = "first"
    SECOND = "second"
    FOURTH = "fourth"


@wire_ordinals({0: "off", 1: "on"})
@wire_default("off")
class Defaulted(Enum):
    """A vocabulary that declares a default, as `MediaStreamProtocol` does with `[DefaultValue]`."""

    OFF = "off"
    ON = "on"


class Bound(AtriumModel):
    """One field per shape the binder has to reach through.

    The field names are the reference's own, because `tests/conformance/test_aliases.py` sweeps
    **every** model in this repository - test models included - against the property names a real
    server sends. A model invented for a unit test is still a model that could ship.
    """

    type: Vocabulary = Vocabulary.FIRST
    method: Vocabulary | None = None
    condition: Defaulted = Defaulted.ON
    protocol: Defaulted | int = Defaulted.ON
    container: str = ""


def test_a_member_arrives_unchanged() -> None:
    assert Bound.model_validate({"Type": Vocabulary.SECOND}).type is Vocabulary.SECOND


def test_the_declared_spelling_binds() -> None:
    assert Bound.model_validate({"Type": "second"}).type is Vocabulary.SECOND


def test_any_case_binds() -> None:
    """The reference registers one converter for its whole pipeline, so a name matches folded.

    Measured on all four vocabularies a device profile carries `[probe:
    tools/probe_playback_info.py, Jellyfin 10.11.11, 2026-09-04]`.
    """
    for spelling in ("SECOND", "Second", "sEcOnD"):
        assert Bound.model_validate({"Type": spelling}).type is Vocabulary.SECOND


def test_an_ordinal_binds_by_the_declared_number_and_not_by_position() -> None:
    """`3` is the fourth member and `2` is nobody, which is the reference's own shape.

    Measured there rather than reasoned: a codec profile typed `0` takes a video source's direct
    play away and one typed `2` does not, where this project declares its audio member first
    `[probe: tools/probe_playback_info.py, Jellyfin 10.11.11, 2026-09-04]`.
    """
    assert Bound.model_validate({"Type": 3}).type is Vocabulary.FOURTH
    with pytest.raises(ValidationError):
        Bound.model_validate({"Type": 2})


def test_an_ordinal_written_as_a_string_binds() -> None:
    """`AllowReadingFromString`, measured in the three forms the reference accepts.

    `1`, `+1` and ` 1 ` all bound to the member ordinal one names on a real request body
    `[probe: tools/probe_playback_info.py, Jellyfin 10.11.11, 2026-09-04]`.
    """
    for spelling in ("1", "+1", " 1 "):
        assert Bound.model_validate({"Type": spelling}).type is Vocabulary.SECOND


def test_a_bool_is_not_an_ordinal() -> None:
    """`isinstance(True, int)` is the trap: `true` is a measured `400` and `1` a measured member.

    A binder that folded the two would answer a client that sent a boolean with the member the
    ordinal one names `[probe: tools/probe_playback_info.py, Jellyfin 10.11.11, 2026-08-29]`.
    """
    with pytest.raises(ValidationError):
        Bound.model_validate({"Type": True})


def test_a_word_no_member_has_still_refuses() -> None:
    """The refusal stays the model's own validation rather than a second one invented here."""
    with pytest.raises(ValidationError):
        Bound.model_validate({"Type": "dash"})


def test_an_empty_string_refuses_where_no_default_is_declared() -> None:
    """The row that proves the fourth class is **not** general.

    An empty string is a `400` on a codec profile's `Type` and on a direct-play entry's `Type`,
    against the protocol's `200` taking `http` as the control `[probe:
    tools/probe_playback_info.py, Jellyfin 10.11.11, 2026-09-03]`.
    """
    with pytest.raises(ValidationError):
        Bound.model_validate({"Type": ""})


def test_an_empty_string_and_a_null_take_a_declared_default() -> None:
    for value in ("", None):
        assert Bound.model_validate({"Condition": value}).condition is Defaulted.OFF


def test_a_union_with_a_number_keeps_an_ordinal_no_member_has() -> None:
    """What the reference answers for the delivery protocol: the raw number, on the wire.

    The binder keeps it; whether it survives to the answer is the field's type, which is what
    behaviours section 2.24 needs for `TranscodingSubProtocol`.
    """
    assert Bound.model_validate({"Protocol": 7}).protocol == 7
    assert Bound.model_validate({"Protocol": "7"}).protocol == 7
    assert Bound.model_validate({"Protocol": 1}).protocol is Defaulted.ON


def test_an_optional_vocabulary_is_reached_through_the_union() -> None:
    assert Bound.model_validate({"Method": "FOURTH"}).method is Vocabulary.FOURTH


def test_a_field_that_is_not_a_vocabulary_is_untouched() -> None:
    """The binder runs per field, so a string field keeps a string that looks like an ordinal."""
    assert Bound.model_validate({"Container": "1"}).container == "1"


def test_the_binder_reads_a_key_in_any_casing() -> None:
    """The two before-validators must not depend on which of them pydantic runs first."""
    assert Bound.model_validate({"tYpE": "SECOND"}).type is Vocabulary.SECOND


def test_an_ordinal_table_must_name_every_member() -> None:
    """A vocabulary that gains a member and not an ordinal does not import.

    Every number after the missing one would otherwise bind to the wrong member, silently.
    """
    with pytest.raises(ValueError, match="no ordinal"):

        @wire_ordinals({0: "first"})
        class Incomplete(Enum):
            FIRST = "first"
            SECOND = "second"


def test_the_ordinal_table_is_the_one_the_other_readers_use() -> None:
    """`ordinals_of` is what keeps the query-string reader and the body binder on one table."""
    assert ordinals_of(Vocabulary) == {
        0: Vocabulary.FIRST,
        1: Vocabulary.SECOND,
        3: Vocabulary.FOURTH,
    }
