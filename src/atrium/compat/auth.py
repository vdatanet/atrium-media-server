# SPDX-License-Identifier: GPL-3.0-or-later
"""Where a token may arrive, and how the client header is spelled.

Extraction and parsing, not resolution: pulling a token out of the five places it can be and
reading a client-identification header are wire-format concerns and belong beside the other
wire-format code. Turning a token into a user is `users/`.

Everything here is a **pure function over a request**, so the whole table runs without a server.

## What was measured, and what the documents had wrong

`[probe: tools/probe_auth_mechanisms.py, Jellyfin 10.11.11, 2026-08-28]`

**There are five mechanisms, not four.** `X-Emby-Authorization` carrying a `Token=` component
authenticates, exactly as `Authorization` does - the reference reads both header names with the
same grammar. Spec section 3.1 listed four, and a client using the historical Emby form would have
been refused by a server that implemented only those.

**Precedence, measured pair by pair:**

    Authorization  >  X-Emby-Authorization  >  X-Emby-Token  >  ?ApiKey= / ?api_key=

**The scheme word is required**, and it is `MediaBrowser` or `Emby`, case-insensitively. Plan
section 6.3 called the prefix "optional in practice"; without it the reference answers `401`, and
so does anything else in its place - `Bearer` included.

**Whitespace around `=` is refused**, which is the one leniency the specification claimed and the
reference does not have: `Token = x` is a `401`. Atrium refuses it too rather than being kinder.
Accepting it would let a client be developed against Atrium and then fail against Jellyfin, which
is the delta that matters even though no working client can be sending it today
(behaviours section 6).

**Component names are case-sensitive** - `token=` is a `401` - while the scheme is not.

Tolerated, all measured: values quoted or bare, no space after a comma, a space *before* a comma,
extra spaces after the scheme, any order, unknown components, and a trailing comma.

**A missing `DeviceId` is not fatal in general.** Plan section 6.3 called it "the one fatal case";
on an ordinary authenticated route the reference answers `200` without it. It is mandatory on
`POST /Users/AuthenticateByName` and nowhere else, so this module reports what it found and
`require_client_authorization` is where that route's rule lives.

See specs/002-authentication-users-and-sessions/plan.md sections 5, 6.1 and 6.3.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from starlette.requests import Request

from atrium.compat.errors import ClientAuthorizationError

#: The scheme words the reference accepts, compared case-insensitively. Anything else, or nothing
#: at all, and the header authenticates nobody.
SCHEMES = frozenset({"mediabrowser", "emby"})

#: One component. **No whitespace is allowed around the `=`**, which is not an oversight: the
#: reference refuses `Token = x`, and matching that is the whole of the argument in the module
#: docstring. The name is matched case-sensitively for the same reason.
COMPONENT = re.compile(r'([A-Za-z][A-Za-z0-9_]*)=(?:"([^"]*)"|([^,]*))')

#: The header names that carry the grammar. In precedence order, which is measured rather than
#: chosen - see the module docstring.
AUTHORIZATION_HEADERS = ("Authorization", "X-Emby-Authorization")

#: The query spellings, after both headers.
QUERY_PARAMETERS = ("ApiKey", "api_key")

#: The component that carries a token, however it arrived.
TOKEN_COMPONENT = "Token"  # noqa: S105 - the name of a header component, not a token


@dataclass(frozen=True, slots=True)
class ClientInfo:
    """What a client says about itself, and possibly the token it presented.

    `token` is kept out of `repr` because this object is built on every request and is exactly the
    sort of thing that ends up in a debug log line (plan section 8.2).
    """

    client: str = ""
    device: str = ""
    device_id: str = ""
    version: str = ""
    token: str | None = field(default=None, repr=False)


def parse_components(value: str) -> dict[str, str] | None:
    """Split a `MediaBrowser Client="…", …` header into its components.

    Returns None when the value carries no acceptable scheme word, which is the reference's own
    answer to a header without one: nothing is read out of it at all.
    """
    scheme, _, rest = value.strip().partition(" ")
    if scheme.lower() not in SCHEMES:
        return None
    found = {}
    for match in COMPONENT.finditer(rest):
        name, quoted, bare = match.group(1), match.group(2), match.group(3)
        found[name] = quoted if quoted is not None else bare.strip()
    return found


def parse_client_authorization(value: str | None) -> ClientInfo | None:
    """Read a client-identification header, or report that there is nothing usable in it.

    None rather than an exception, because whether an absent or unreadable header matters is the
    **route's** decision and not this function's: `AuthenticateByName` requires one, and every
    other route in the project is happy without.
    """
    if not value:
        return None
    components = parse_components(value)
    if components is None:
        return None
    return ClientInfo(
        client=components.get("Client", ""),
        device=components.get("Device", ""),
        device_id=components.get("DeviceId", ""),
        version=components.get("Version", ""),
        token=components.get(TOKEN_COMPONENT) or None,
    )


def require_client_authorization(value: str | None) -> ClientInfo:
    """The rule `POST /Users/AuthenticateByName` applies, and no other route does.

    A header that is absent, carries no scheme, or names no device is a `400` there - a `4xx` that
    is deliberately not `401`, because a client reading it as one tells its user that their
    password is wrong (spec section 3.3).
    """
    info = parse_client_authorization(value)
    if info is None:
        raise ClientAuthorizationError(
            "X-Emby-Authorization is missing or unreadable. It must carry the MediaBrowser scheme."
        )
    if not info.device_id:
        raise ClientAuthorizationError(
            "X-Emby-Authorization carries no DeviceId, which is what identifies a session."
        )
    return info


def client_info(request: Request) -> ClientInfo | None:
    """Whichever of the two headers carries a readable client identification, in order."""
    for header in AUTHORIZATION_HEADERS:
        info = parse_client_authorization(request.headers.get(header))
        if info is not None:
            return info
    return None


def extract_token(request: Request) -> str | None:
    """The token this request presents, in the order the reference resolves them.

    First hit wins, and the order is measured rather than arbitrary: a client that sets a header
    once when the connection is built and assembles URLs from a template sends two, and they
    disagree exactly when one of them is stale.
    """
    for header in AUTHORIZATION_HEADERS:
        components = parse_components(request.headers.get(header) or "")
        if components:
            token = components.get(TOKEN_COMPONENT)
            if token:
                return token

    direct = request.headers.get("X-Emby-Token")
    if direct:
        return direct

    for parameter in QUERY_PARAMETERS:
        value = request.query_params.get(parameter)
        if value:
            return value
    return None


__all__ = [
    "AUTHORIZATION_HEADERS",
    "COMPONENT",
    "QUERY_PARAMETERS",
    "SCHEMES",
    "TOKEN_COMPONENT",
    "ClientInfo",
    "client_info",
    "extract_token",
    "parse_client_authorization",
    "parse_components",
    "require_client_authorization",
]
