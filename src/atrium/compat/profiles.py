# SPDX-License-Identifier: GPL-3.0-or-later
"""The two JSON serialisations the reference offers, and how a client asks for one.

Every operation in the reference's OpenAPI document declares three response content types -
`application/json`, `application/json; profile="PascalCase"` and
`application/json; profile="CamelCase"`. They are three names for **two** behaviours: the profile
selects an output formatter, and the camelCase one really does emit camelCase property names.
`[probe: tools/probe_content_type_profiles.py, Jellyfin 10.11.11, 2026-08-26]`
`[source: Jellyfin.Server/Extensions/ApiServiceCollectionExtensions.cs:126-129,
src/Jellyfin.Extensions/Json/JsonDefaults.cs:21,55-58 @ v10.11.11]`

A client that asks for camelCase and is answered in PascalCase does not get a degraded response.
It gets an empty object out of its decoder, which is the failure mode of
docs/compatibility/behaviours.md section 1.1 exactly.

**Four measured rules, none of which are in the document.**

1. **The match is on the media type's parameter, leniently.** `profile=CamelCase` unquoted and
   `profile="camelcase"` both match. A **`charset` parameter alongside it does not** - that
   request is served the plain formatter. An unknown profile falls back the same way.
2. **Ranking is ordinary content negotiation.** With equal quality the first acceptable type wins,
   so `application/json, application/json; profile="CamelCase"` is PascalCase; with `q=` values
   the higher one wins.
3. **The response echoes the profile that matched**, canonically spelled and before the charset:
   `application/json; profile="CamelCase"; charset=utf-8`. It is echoed on every JSON response,
   including a bare string body like `/System/Ping`'s. Refusals carry no content type at all, so
   they echo nothing.
4. **The conversion is .NET's `JsonNamingPolicy.CamelCase`**, not "lower the first letter": a
   leading run of capitals lowers all but the last of them. Over the 1043 names of the pinned
   document the two rules disagree exactly once, on `UICulture`.

**Where the conversion happens is the whole design.** Property names are converted at every depth
and **dictionary keys are not converted at all** - `ProviderIds`, `ImageTags` and `ImageBlurHashes`
keep their keys, because the reference sets `PropertyNamingPolicy` and never sets
`DictionaryKeyPolicy`. Once a response is bytes, or even a plain `dict`, nothing can tell a
property from a key. So the rename is done by `AtriumModel`'s own serialiser, where a field is
still a field, and this module only decides *which* serialisation was asked for.

The decision travels in a `ContextVar` rather than through the web framework's serialisation call,
because that call does not take a context to pass one through. A context variable set by a
middleware is visible to everything the request goes on to do, in the same task, and is reset when
it finishes - so two concurrent requests asking for two profiles cannot see each other's.

See specs/001-server-identity-and-discovery/spec.md section 3.0 rule 2 and plan.md section 5.
"""

from __future__ import annotations

from contextvars import ContextVar
from enum import Enum

from starlette.types import ASGIApp, Receive, Scope, Send

#: What the reference sends when no profile matched: behaviours section 1.10.
JSON_MEDIA_TYPE = "application/json; charset=utf-8"


class Profile(Enum):
    """Which serialisation a response uses. The value is the reference's own spelling."""

    #: No profile matched. PascalCase, and the content type says nothing about it.
    PLAIN = ""
    PASCAL = "PascalCase"
    CAMEL = "CamelCase"

    @property
    def media_type(self) -> str:
        if self is Profile.PLAIN:
            return JSON_MEDIA_TYPE
        # Parameter order is the reference's: the profile, then the charset.
        return f'application/json; profile="{self.value}"; charset=utf-8'


#: The profile of the request being served. `PLAIN` outside a request, which is what a direct
#: `model_dump()` in a test or a script gets, and the safe answer for anything that forgets.
CURRENT: ContextVar[Profile] = ContextVar("atrium_content_profile", default=Profile.PLAIN)

_BY_NAME = {profile.value.lower(): profile for profile in Profile if profile is not Profile.PLAIN}

_JSON_TYPES = frozenset({"application/json", "application/*", "*/*"})


def current() -> Profile:
    return CURRENT.get()


def camel_case(name: str) -> str:
    """Convert a property name the way .NET's `JsonNamingPolicy.CamelCase` does.

    Not "lower the first letter": a **leading run of capitals** is lowered except for the last of
    them, so `UICulture` becomes `uiCulture` and not `uICulture`. `ETag` becomes `eTag` under both
    rules, which is why the difference is so easy to miss - a spot check almost certainly lands on
    a name where the wrong rule is right.

    Verified against 293 property names measured on a live reference, 281 of which it converts:
    every one agreed. `[probe: tools/probe_content_type_profiles.py, Jellyfin 10.11.11,
    2026-08-26]`
    """
    if not name or not name[0].isupper():
        return name

    characters = list(name)
    for index, character in enumerate(characters):
        if index == 1 and not character.isupper():
            break
        following = characters[index + 1] if index + 1 < len(characters) else None
        if index > 0 and following is not None and not following.isupper():
            break
        characters[index] = character.lower()
    return "".join(characters)


def _parse(accept: str) -> list[tuple[str, dict[str, str], float]]:
    """Split an `Accept` header into (media type, parameters, quality), most preferred first."""
    candidates: list[tuple[str, dict[str, str], float]] = []
    for raw in accept.split(","):
        parts = [part.strip() for part in raw.split(";") if part.strip()]
        if not parts:
            continue
        media_type = parts[0].lower()
        parameters: dict[str, str] = {}
        quality = 1.0
        for part in parts[1:]:
            name, _, value = part.partition("=")
            name = name.strip().lower()
            value = value.strip().strip('"')
            if name == "q":
                try:
                    quality = float(value)
                except ValueError:
                    quality = 0.0
            else:
                parameters[name] = value
        candidates.append((media_type, parameters, quality))
    # Stable, so equal quality keeps the client's own order - which is what decides
    # `application/json, application/json; profile="CamelCase"`.
    return sorted(candidates, key=lambda candidate: -candidate[2])


def negotiate(accept: str | None) -> Profile:
    """Which serialisation this `Accept` header asks for."""
    if not accept:
        return Profile.PLAIN

    for media_type, parameters, quality in _parse(accept):
        if quality <= 0 or media_type not in _JSON_TYPES:
            continue
        # Exactly one parameter, and it is the profile. A charset beside it means the reference
        # serves the plain formatter, which is measured rather than reasoned.
        if set(parameters) == {"profile"}:
            matched = _BY_NAME.get(parameters["profile"].lower())
            if matched is not None:
                return matched
        # `application/json` with anything else - or nothing else - is the plain formatter, and
        # being earlier in the ranking is what makes it win.
        return Profile.PLAIN
    return Profile.PLAIN


class ContentProfileMiddleware:
    """Decide the profile once per request, where every serialiser downstream can see it.

    Raw ASGI, like everything else in this project: `BaseHTTPMiddleware` buffers responses, which
    is wrong for the delivery feature 008 adds - and it also runs the application in a separate
    task, which is exactly what a context variable does not survive.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        accepted = b", ".join(
            value for name, value in scope.get("headers", ()) if name.lower() == b"accept"
        )
        token = CURRENT.set(negotiate(accepted.decode("latin-1") or None))
        try:
            await self.app(scope, receive, send)
        finally:
            CURRENT.reset(token)


__all__ = [
    "CURRENT",
    "JSON_MEDIA_TYPE",
    "ContentProfileMiddleware",
    "Profile",
    "camel_case",
    "current",
    "negotiate",
]
