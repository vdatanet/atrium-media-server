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

from collections.abc import Callable, Mapping
from enum import Enum
from types import UnionType
from typing import Any, ClassVar, Union, get_args, get_origin

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
    `[probe: tools/probe_auth_mechanisms.py, Jellyfin 10.11.11, 2026-08-28]`

    Annotate the field and the conversion reaches inside it:

        policy: Annotated[dict[str, Any] | None, PropertyKeyed] = None
    """


#: Every vocabulary a request body binds, against the numbers the reference **declares** for it.
#: Written by `wire_ordinals`, read by the binder below and by `ordinals_of`.
_WIRE_ORDINALS: dict[type[Enum], Mapping[int, Enum]] = {}

#: The member an enumeration falls back to for a `null` or an empty string, where it declares one.
#: Written by `wire_default`. Empty for every enumeration but the delivery protocol's.
_WIRE_DEFAULTS: dict[type[Enum], Enum] = {}


def wire_ordinals[E: Enum](declared: Mapping[int, str]) -> Callable[[type[E]], type[E]]:
    """Register the numbers the reference's own enumeration declares for these members.

    A vocabulary bound on a request body binds **by ordinal** as well as by name, because the
    reference reads a number - or a string of digits - through one globally registered converter
    `[source: src/Jellyfin.Extensions/Json/JsonDefaults.cs:34, 42 @ v10.11.11]`. Measured on all
    four of the enumerations this body carries `[probe: tools/probe_playback_info.py, Jellyfin
    10.11.11, 2026-09-04]`.

    **The number is declared, not counted**, and that is the whole reason this is a registration
    rather than `list(vocabulary).index(member)`. Two of the four say so on the wire: `CodecType`
    declares `Video = 0` where this project's own enumeration declares its audio member first, so
    a counted binder answers `0` with the opposite member and a codec profile constrains the
    stream it was not meant to; and `ProfileConditionValue` **skips 15**, so `NumStreams` is 25
    where counting makes it 24 - measured, `25` binds and `15` binds to nothing `[source:
    MediaBrowser.Model/Dlna/CodecType.cs, MediaBrowser.Model/Dlna/ProfileConditionValue.cs @
    v10.11.11]`. `SUBTITLE_METHOD_ORDINALS` had said as much in a comment since 011 T9; this is
    that sentence given somewhere to be enforced.

    Every member must be named exactly once, or the class does not import: a vocabulary that
    gained a member and not an ordinal would bind every number after it to the wrong one.
    """

    def register(vocabulary: type[E]) -> type[E]:
        by_ordinal = {ordinal: vocabulary(value) for ordinal, value in declared.items()}
        missing = sorted(str(one.value) for one in vocabulary if one not in by_ordinal.values())
        if missing or len(by_ordinal) != len(declared):
            raise ValueError(
                f"{vocabulary.__name__} declares members with no ordinal: {missing or 'duplicated'}"
            )
        _WIRE_ORDINALS[vocabulary] = by_ordinal
        return vocabulary

    return register


def wire_default[E: Enum](value: str) -> Callable[[type[E]], type[E]]:
    """Register the member a `null` or an empty string falls back to, for the one kind of
    enumeration that has one.

    The reference's default is `[DefaultValue]` on the **enum type**, and the converter that
    applies it is created by a factory whose `CanConvert` requires that attribute
    `[source: src/Jellyfin.Extensions/Json/Converters/JsonDefaultStringEnumConverterFactory.cs:20
    @ v10.11.11]`. So this is a property of the type and not a table in the binder, and it is
    **not** general: T1 posted an empty string to two enumerations that declare no default - a
    codec profile's `Type` and a direct-play entry's `Type` - and each is a `400` where the
    protocol's is a `200` taking `http` `[probe: tools/probe_playback_info.py, Jellyfin 10.11.11,
    2026-09-03]`.

    Written as a decorator rather than as an attribute inside the enum body, which is the trap
    this shape avoids: `WIRE_DEFAULT = "http"` written between the members would be an *alias* of
    that member rather than a class variable - a third name a `for one in Vocabulary` loop does
    not yield and an `is` comparison does.
    """

    def register(vocabulary: type[E]) -> type[E]:
        _WIRE_DEFAULTS[vocabulary] = vocabulary(value)
        return vocabulary

    return register


def ordinals_of[E: Enum](vocabulary: type[E]) -> Mapping[int, E]:
    """The registered ordinal table, for the two readers that need it outside a request body.

    A delivery address spells a subtitle method as a number too (011 T11, `media/decision.py`'s
    `method_named`), and two copies of one table would be two answers to one question about the
    reference.
    """
    return _WIRE_ORDINALS[vocabulary]  # type: ignore[return-value]


def declares_ordinals(vocabulary: type[Enum]) -> bool:
    """Whether this vocabulary has a table at all, for the sweep that says every one must.

    A model bound to an enumeration nobody registered refuses every number the reference accepts,
    which is a `400` on a property nobody remembered - so `tests/conformance/test_aliases.py` asks
    this of every field, the way it asks whether a name is one the reference uses.
    """
    return vocabulary in _WIRE_ORDINALS


def _vocabulary_in(annotation: Any) -> type[Enum] | None:
    """The enumeration a field is bound to, through an optional or a union, or `None`.

    `Vocabulary | None` and `Vocabulary | int` are both fields this binder must reach: the second
    is how an ordinal no member has survives to the wire as a number, which is what the reference
    answers for the delivery protocol (behaviours section 2.24).
    """
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return annotation
    if get_origin(annotation) in (Union, UnionType):
        for one in get_args(annotation):
            found = _vocabulary_in(one)
            if found is not None:
                return found
    return None


def _digits(value: str) -> int | None:
    """The number a string of digits names, as the reference's own converter reads one.

    Measured rather than assumed, on the body path and not only on the query one: `1`, `+1` and
    ` 1 ` all bind to the member ordinal one names `[probe: tools/probe_playback_info.py,
    Jellyfin 10.11.11, 2026-09-04]`. `isascii` keeps a non-ASCII digit out, which the platform
    conversion refuses too (`media/decision.py:_ordinal_of`, measured on the query side).
    """
    stripped = value.strip()
    digits = stripped[1:] if stripped[:1] in {"+", "-"} else stripped
    if digits.isascii() and digits.isdigit():
        return int(stripped)
    return None


def _bound_value(vocabulary: type[Enum], value: Any) -> Any:
    """One value read into one vocabulary, in the four classes the reference answers in.

    A member is unchanged; a **bool** is unchanged, because `isinstance(True, int)` is Python's
    trap and the reference's answers are opposite - `true` is a measured `400` and the ordinal
    `1` a measured member; a number or a string of digits is the ordinal's member, and the raw
    number where no member has it; a name matches folded; and `null` or `""` takes the declared
    default **only where one is registered**. Anything else is handed on unchanged, so the
    refusal stays the model's own validation rather than a second refusal invented here.
    """
    if isinstance(value, (Enum, bool)):
        return value
    ordinals = _WIRE_ORDINALS.get(vocabulary, {})
    if isinstance(value, int):
        return ordinals.get(value, value)
    if isinstance(value, str):
        number = _digits(value)
        if number is not None:
            return ordinals.get(number, number)
        if value == "":
            return _WIRE_DEFAULTS.get(vocabulary, value)
        folded = value.lower()
        return next((one for one in vocabulary if str(one.value).lower() == folded), value)
    if value is None:
        return _WIRE_DEFAULTS.get(vocabulary, value)
    return value


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

    #: Wire names whose `None` still reaches the body as an explicit `null`.
    #:
    #: Empty here and on almost every subclass, because the null-suppression below is global and
    #: measured (behaviours section 1.7) - but the same measurement found the exception: the
    #: reference sends `"ChannelId": null` on **every item of every response**, 208 of 208 sampled,
    #: where its own configuration says a null is omitted
    #: `[probe: tools/probe_item_shapes.py, Jellyfin 10.11.11, 2026-08-27]`. What defeats the
    #: setting there is unestablished; that it is defeated is not. A subclass that must reproduce
    #: such an exception names the wire spelling here, and the key is emitted in place, profile
    #: conversion included, rather than re-inserted by hand after serialisation.
    NULL_KEPT: ClassVar[frozenset[str]] = frozenset()

    #: The reference's own name for this type, as its JSON deserialiser spells it when it refuses
    #: a body that omits a required property: `JSON deserialization for type '<this>' was missing
    #: required properties including: 'Name'.` Empty on every model whose body has no required
    #: property, which is all of them but one - and an empty value keeps the refusal 007 measured
    #: rather than inventing a sentence
    #: `[probe: tools/probe_playlist_creation.py, Jellyfin 10.11.11, 2026-08-31]`.
    #:
    #: It is a fact about the **wire**, not about the reference's code: the string reaches a
    #: client, so reproducing it is Principle I in the same way `Error processing request.` is,
    #: and nothing here is derived from how the reference computes it. compat/errors.py.
    WIRE_TYPE: ClassVar[str] = ""

    #: The reference's own name for the enumeration behind a vocabulary property, keyed by the
    #: property's **wire** spelling: the refusal for a value no member matches names that type
    #: (`The JSON value could not be converted to <this>.`) and nothing else can supply it. Same
    #: rule as `WIRE_TYPE`: a property absent from this map keeps the 007 shape.
    WIRE_ENUM_TYPES: ClassVar[Mapping[str, str]] = {}

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
        [probe: tools/probe_public_info.py, Jellyfin 10.11.11, 2026-08-28]

        This is a single global rule rather than the per-property judgement
        docs/compatibility/behaviours.md section 1.7 assumed it might be, which is why it belongs
        here rather than in a `response_model_exclude_none` on every route - a per-route flag is
        one someone eventually forgets.
        """
        serialised = {
            key: value
            for key, value in handler(self).items()
            if value is not None or key in self.NULL_KEPT
        }
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

        known = cls._names_by_key()
        remapped: dict[Any, Any] = {}
        for key, value in data.items():
            if not isinstance(key, str) or key in cls.model_fields:
                remapped[key] = value
                continue
            target = known.get(key.lower())
            remapped[target if target is not None else key] = value
        return remapped

    @model_validator(mode="before")
    @classmethod
    def _bind_vocabularies(cls, data: Any) -> Any:
        """Read every enumerated property the reference's own binder would, in its four classes.

        One converter is registered for the reference's whole JSON pipeline, so **case-insensitive
        names and ordinals reach every enumerated value a body carries** rather than one property
        `[source: src/Jellyfin.Extensions/Json/JsonDefaults.cs:34, 42 @ v10.11.11]`. Measured on
        the four this negotiation binds - a direct-play entry's `Type`, a codec profile's `Type`,
        and a condition's `Condition` and `Property`: each takes an altered case and each takes
        its ordinal, where a strictly-cased field is a `400` the reference answers `200` to
        `[probe: tools/probe_playback_info.py, Jellyfin 10.11.11, 2026-09-04]`,
        `[probe: tools/probe_subtitle_negotiation.py, Jellyfin 10.11.11, 2026-08-30]`.

        **What it must not make general is the fourth class.** An empty string takes the declared
        default only where the enumeration declares one, which is a registration (`wire_default`)
        and not a rule: measured, an empty string is a `400` on the two vocabularies that declare
        none `[probe: tools/probe_playback_info.py, Jellyfin 10.11.11, 2026-09-03]`.

        **And nothing outside a request body.** A query parameter naming no member is a `200` that
        ignores the value rather than a `400` (behaviours section 1.12,
        `media/decision.py:method_named`), and this runs only on construction from a mapping. Like
        `_accept_any_casing`, it costs a well-formed body nothing: a value that already fits its
        vocabulary is returned untouched.
        """
        if not isinstance(data, dict):
            return data
        vocabularies = cls._vocabularies()
        if not vocabularies:
            return data

        known = cls._names_by_key()
        bound: dict[Any, Any] = {}
        for key, value in data.items():
            target = key if key in cls.model_fields else None
            if target is None and isinstance(key, str):
                target = known.get(key.lower())
            vocabulary = vocabularies.get(target) if target is not None else None
            bound[key] = value if vocabulary is None else _bound_value(vocabulary, value)
        return bound

    @classmethod
    def _names_by_key(cls) -> Mapping[str, str]:
        """Every spelling a client may use for this model's fields, folded. Once per class."""
        cached = cls.__dict__.get("__names_by_key__")
        if cached is None:
            known: dict[str, str] = {}
            for name, field in cls.model_fields.items():
                known[name.lower()] = name
                known[(field.alias or atrium_alias(name)).lower()] = name
            cached = known
            cls.__names_by_key__ = cached  # type: ignore[attr-defined]
        return cached

    @classmethod
    def _vocabularies(cls) -> Mapping[str, type[Enum]]:
        """This model's fields that are bound to an enumeration. Computed once per class."""
        cached = cls.__dict__.get("__vocabularies__")
        if cached is None:
            found: dict[str, type[Enum]] = {}
            for name, field in cls.model_fields.items():
                vocabulary = _vocabulary_in(field.annotation)
                if vocabulary is not None:
                    found[name] = vocabulary
            cached = found
            cls.__vocabularies__ = cached  # type: ignore[attr-defined]
        return cached


__all__ = [
    "AtriumModel",
    "PropertyKeyed",
    "declares_ordinals",
    "ordinals_of",
    "wire_default",
    "wire_ordinals",
]
