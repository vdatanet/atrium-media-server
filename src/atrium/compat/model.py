# SPDX-License-Identifier: GPL-3.0-or-later
"""The base class every request and response model inherits.

Principle I says a client must not be able to tell Atrium from the reference, and the most likely
way to break that is not a wrong endpoint but a wrong casing: Python's ecosystem defaults to
snake_case everywhere, and a camelCase body is not a lesser response to a client's decoder, it is
an empty object.

So the correct casing is the default and producing anything else takes a deliberate override, which
the conformance sweep then fails. A route author cannot forget.

See docs/compatibility/behaviours.md section 1.1 and
specs/001-server-identity-and-discovery/plan.md section 5.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, model_serializer, model_validator
from pydantic_core.core_schema import SerializerFunctionWrapHandler

from atrium.compat.aliases import atrium_alias
from atrium.compat.profiles import Profile, camel_case, current


class PropertyKeyed:
    """Marker: this mapping's keys are **property names**, not data.

    The rule that dictionary keys are never converted is right for `ProviderIds` and `ImageTags`,
    whose keys are values a client chose. It is wrong for a field that is an *object* on the
    reference and a mapping here - `Policy` and `Configuration` are the two, because v1 carries the
    31 policy properties it does not act on rather than declaring them.

    Measured: under the CamelCase profile the reference sends `policy.isAdministrator` and
    `configuration.audioLanguagePreference`, so a mapping left alone would send `IsAdministrator`
    where the reference sends `isAdministrator` - on every one of those properties.
    `[probe: manual request, Jellyfin 10.11.11, 2026-08-26]`

    Annotate the field and the conversion reaches inside it:

        policy: Annotated[dict[str, Any] | None, PropertyKeyed] = None
    """


def _convert_keys(value: Any) -> Any:
    """camelCase every key of a property-keyed value, at every depth."""
    if isinstance(value, dict):
        return {camel_case(str(key)): _convert_keys(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_convert_keys(item) for item in value]
    return value


class AtriumModel(BaseModel):
    """PascalCase on the wire, snake_case in Python, and lenient about what arrives.

    `serialize_by_alias` matters more than it looks: without it, `model_dump()` is correct only
    when the caller remembers `by_alias=True`, and the one place someone forgets is the one place
    a client sees snake_case.
    """

    model_config = ConfigDict(
        alias_generator=atrium_alias,
        populate_by_name=True,  # accept the Python spelling as well as the wire spelling
        serialize_by_alias=True,  # PascalCase without the caller having to ask
        extra="ignore",  # unknown request properties are ignored, not rejected
    )

    @model_serializer(mode="wrap")
    def _for_the_wire(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        """Drop null properties and apply the requested serialisation profile.

        **The profile is applied here, and here is the only place it can be applied correctly.**
        The reference converts property names at every depth and leaves **dictionary keys** alone -
        `ProviderIds`, `ImageTags` - and by the time a response is a plain `dict`, nothing can tell
        one from the other. A field is still a field here, so a nested model renames itself and a
        `dict[str, ...]` field's keys are never touched. See atrium.compat.profiles.

        And the nulls: the reference drops them globally, by one setting.

        The reference configures `DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull`
        for its whole JSON pipeline, so a property with no value is **absent** rather than `null`.
        Measured too: `/System/Info` declares `PackageName` and does not send it.
        [source: src/Jellyfin.Extensions/Json/JsonDefaults.cs:33,
        Jellyfin.Server/Extensions/ApiServiceCollectionExtensions.cs:148 @ v10.11.11]
        [probe: manual request, Jellyfin 10.11.11, 2026-08-26]

        This is a single global rule rather than the per-property judgement
        docs/compatibility/behaviours.md section 1.7 assumed it might be, which is why it belongs
        here rather than in a `response_model_exclude_none` on every route - a per-route flag is
        one someone eventually forgets.
        """
        serialised = {key: value for key, value in handler(self).items() if value is not None}
        if current() is Profile.CAMEL:
            keyed = self._property_keyed()
            return {
                camel_case(key): _convert_keys(value) if key in keyed else value
                for key, value in serialised.items()
            }
        return serialised

    @classmethod
    def _property_keyed(cls) -> frozenset[str]:
        """The wire names of this model's `PropertyKeyed` fields. Computed once per class."""
        cached = cls.__dict__.get("__property_keyed__")
        if cached is None:
            cached = frozenset(
                field.alias or atrium_alias(name)
                for name, field in cls.model_fields.items()
                if any(
                    item is PropertyKeyed or item is PropertyKeyed.__class__
                    for item in field.metadata
                )
            )
            cls.__property_keyed__ = cached  # type: ignore[attr-defined]
        return cached

    @model_validator(mode="before")
    @classmethod
    def _accept_any_casing(cls, data: Any) -> Any:
        """Match incoming keys case-insensitively, as the reference's model binder does.

        `populate_by_name` accepts the field name and the alias, and nothing else. That is not what
        the reference does: it is an ASP.NET Core application, and its JSON binder matches property
        names **case-insensitively** - so a client posting `{"username": ...}` to a property
        declared `Username` is served, and a client posting the same body to Atrium would not be.

        The fast path is untouched: this only builds a lookup when a key does not already match
        something the model knows, which for a well-behaved client is never.
        """
        if not isinstance(data, dict):
            return data

        known: dict[str, str] = {}
        for name, field in cls.model_fields.items():
            known[name.lower()] = name
            alias = field.alias or atrium_alias(name)
            known[alias.lower()] = name

        remapped: dict[Any, Any] = {}
        for key, value in data.items():
            if not isinstance(key, str) or key in cls.model_fields:
                remapped[key] = value
                continue
            target = known.get(key.lower())
            remapped[target if target is not None else key] = value
        return remapped


__all__ = ["AtriumModel", "PropertyKeyed"]
