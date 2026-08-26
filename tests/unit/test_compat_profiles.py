# SPDX-License-Identifier: GPL-3.0-or-later
"""The two serialisations, how a client asks for one, and where the conversion is allowed to reach.

The reference's rules here were measured, not read: the OpenAPI document declares three content
types against one schema and says nothing about two of them serialising differently.
[probe: tools/probe_content_type_profiles.py, Jellyfin 10.11.11, 2026-08-26]

**The models below use real reference property names on purpose.** Every `AtriumModel` subclass
that exists anywhere - including one defined inside a test - is walked by the alias sweep, so a
model invented here with an invented field name would fail that sweep depending on which file
pytest reached first.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import pytest

from atrium.compat.model import AtriumModel
from atrium.compat.profiles import CURRENT, Profile, camel_case, negotiate

# --------------------------------------------------------------------------------------------
# Asking for a profile
# --------------------------------------------------------------------------------------------

#: Every row was issued against a real reference and its answer recorded.
#: [probe: tools/probe_content_type_profiles.py, Jellyfin 10.11.11, 2026-08-26]
NEGOTIATION = [
    ("application/json", Profile.PLAIN),
    ('application/json; profile="PascalCase"', Profile.PASCAL),
    ('application/json; profile="CamelCase"', Profile.CAMEL),
    # The parameter is matched leniently: no space, no quotes, any casing of the value.
    ('application/json;profile="CamelCase"', Profile.CAMEL),
    ("application/json; profile=CamelCase", Profile.CAMEL),
    ('application/json; profile="camelcase"', Profile.CAMEL),
    ('application/json; profile="CAMELCASE"', Profile.CAMEL),
    # A charset beside the profile stops it matching. Measured, and the opposite of what anyone
    # would guess - which is the whole reason this table is a table.
    ('application/json; charset=utf-8; profile="CamelCase"', Profile.PLAIN),
    # A quality parameter is not an extra parameter.
    ('application/json; profile="CamelCase"; q=1.0', Profile.CAMEL),
    # Ordinary content negotiation: equal quality keeps the client's order, q= overrides it.
    ('application/json, application/json; profile="CamelCase"', Profile.PLAIN),
    ('application/json; profile="CamelCase", application/json', Profile.CAMEL),
    ('application/json;q=0.5, application/json; profile="CamelCase";q=0.9', Profile.CAMEL),
    # A profile that does not exist falls back rather than failing.
    ('application/json; profile="Nonsense"', Profile.PLAIN),
    # Anything else is the plain formatter too - the reference does not answer 406 here.
    ("application/xml", Profile.PLAIN),
    ("*/*", Profile.PLAIN),
    ("", Profile.PLAIN),
]


@pytest.mark.parametrize(("accept", "expected"), NEGOTIATION)
def test_negotiation(accept: str, expected: Profile) -> None:
    assert negotiate(accept) is expected


def test_a_missing_accept_header_is_the_plain_profile() -> None:
    assert negotiate(None) is Profile.PLAIN


def test_the_content_type_echoes_the_profile_before_the_charset() -> None:
    """Parameter order is the reference's, and a golden test compares these bytes."""
    assert Profile.PLAIN.media_type == "application/json; charset=utf-8"
    assert Profile.PASCAL.media_type == 'application/json; profile="PascalCase"; charset=utf-8'
    assert Profile.CAMEL.media_type == 'application/json; profile="CamelCase"; charset=utf-8'


# --------------------------------------------------------------------------------------------
# Converting a name
# --------------------------------------------------------------------------------------------

#: Measured pairs. 293 property names were read from nine endpoints under both profiles and every
#: one of the 281 conversions agreed with this function; these are the ones worth writing down.
#: [probe: tools/probe_content_type_profiles.py, Jellyfin 10.11.11, 2026-08-26]
CONVERSIONS = [
    ("LocalAddress", "localAddress"),
    ("ServerName", "serverName"),
    ("Id", "id"),
    ("StartupWizardCompleted", "startupWizardCompleted"),
    ("OperatingSystemDisplayName", "operatingSystemDisplayName"),
    # The one name in the pinned document where "lower the first letter" gives a different answer.
    ("UICulture", "uiCulture"),
    # Already camelCase, or not a property name at all: left alone.
    ("id", "id"),
    ("", ""),
]


@pytest.mark.parametrize(("pascal", "camel"), CONVERSIONS)
def test_camel_case(pascal: str, camel: str) -> None:
    assert camel_case(pascal) == camel


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        # A leading run of capitals lowers all but the last of them.
        ("ETag", "eTag"),
        ("AB", "ab"),
        ("ABc", "aBc"),
        # A run that is not leading is untouched, which is why `IsHD` looks like the naive rule.
        ("IsHD", "isHD"),
        ("Is4K", "is4K"),
    ],
)
def test_camel_case_follows_the_reference_policy_not_the_obvious_one(
    name: str, expected: str
) -> None:
    """.NET's `JsonNamingPolicy.CamelCase`, which is what the reference configures.

    `ETag` and `IsHD` convert identically under both rules, and `UICulture` does not. A spot check
    almost certainly lands on one of the first two, which is how a wrong rule survives review.
    """
    assert camel_case(name) == expected


def test_the_naive_rule_and_this_one_differ_exactly_once_in_the_pinned_document() -> None:
    """Over the reference's own 1043 property names, and the one is the one that was measured."""
    import json
    from pathlib import Path

    index = Path(__file__).resolve().parents[2] / "docs/compatibility/property-names.json"
    names = json.loads(index.read_text(encoding="utf-8"))["names"]
    disagreements = {name for name in names if camel_case(name) != name[:1].lower() + name[1:]}
    assert disagreements == {"UICulture"}


# --------------------------------------------------------------------------------------------
# Where the conversion reaches
# --------------------------------------------------------------------------------------------


@contextmanager
def serialising_as(profile: Profile) -> Iterator[None]:
    token = CURRENT.set(profile)
    try:
        yield
    finally:
        CURRENT.reset(token)


class _Nested(AtriumModel):
    local_address: str = ""
    server_name: str | None = None


class _Outer(AtriumModel):
    #: A dictionary. Its keys are data - `Tmdb`, `Primary` - and the reference never converts them.
    provider_ids: dict[str, str] = {}  # noqa: RUF012 - pydantic copies this per instance
    cast_receiver_applications: list[_Nested] = []  # noqa: RUF012
    startup_wizard_completed: bool = False


def test_the_plain_profile_serialises_pascal_case() -> None:
    with serialising_as(Profile.PLAIN):
        assert _Nested(local_address="x").model_dump(mode="json") == {"LocalAddress": "x"}


def test_the_camel_profile_converts_property_names() -> None:
    with serialising_as(Profile.CAMEL):
        assert _Nested(local_address="x").model_dump(mode="json") == {"localAddress": "x"}


def test_it_converts_at_every_depth() -> None:
    """A nested model renames itself: the profile is applied by the model, not by its caller."""
    value = _Outer(cast_receiver_applications=[_Nested(local_address="x")])
    with serialising_as(Profile.CAMEL):
        dumped = value.model_dump(mode="json")
    assert list(dumped) == ["providerIds", "castReceiverApplications", "startupWizardCompleted"]
    assert dumped["castReceiverApplications"] == [{"localAddress": "x"}]


def test_it_does_not_convert_dictionary_keys() -> None:
    """The rule that decides where this code can live.

    The reference sets `PropertyNamingPolicy` and never sets `DictionaryKeyPolicy`, so
    `ProviderIds` keeps `Tmdb` and `ImageTags` keeps `Primary`.
    [source: src/Jellyfin.Extensions/Json/JsonDefaults.cs:55-58 @ v10.11.11]
    Anything that converted the finished response would rename these too, and nothing downstream
    could tell that it should not.
    """
    value = _Outer(provider_ids={"Tmdb": "1", "MusicBrainzAlbum": "2"})
    with serialising_as(Profile.CAMEL):
        dumped = value.model_dump(mode="json")
    assert dumped["providerIds"] == {"Tmdb": "1", "MusicBrainzAlbum": "2"}


def test_nulls_are_still_absent_under_the_camel_profile() -> None:
    """Two rules in one serialiser, and the second must not switch the first off."""
    with serialising_as(Profile.CAMEL):
        assert _Nested(local_address="x").model_dump(mode="json") == {"localAddress": "x"}
