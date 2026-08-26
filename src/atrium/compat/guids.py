# SPDX-License-Identifier: GPL-3.0-or-later
"""Identifiers: thirty-two lowercase hexadecimal characters.

The reference serialises every identifier in .NET's `"N"` format - 32 hex characters, no dashes,
no braces - and parses them with `Guid.TryParse`, which accepts the dashed form, braces and any
casing. So this module is **lenient on the way in and strict on the way out**: a client that stored
`0d41983a5d18d53282f56e7460e2c2cd` and sends back `{0D41983A-5D18-D532-82F5-6E7460E2C2CD}` is
served, and every identifier this server emits is the canonical form.
`[source: Jellyfin.Api/Controllers/ItemsController.cs:974 binds Guid route parameters;
Jellyfin.Api/Helpers/MediaInfoHelper.cs:142 emits ToString("N") @ v10.11.11]`

Identifiers are **derived, never allocated**: no autoincrement column reaches a client. Clients key
their caches, favourites and resume positions on these strings, so an identifier that changes when
a library is rescanned silently discards a user's state. `derive` is the mechanism, and feature 003
is its first real caller.

**Reproducing the reference's exact identifier for the same file is not a goal.** It derives from a
C# type name and an absolute path, and matching that would mean reproducing an implementation
detail of a codebase this project does not fork (Principle IV). What is reproduced is the *shape*
and the *stability guarantee*. See docs/compatibility/behaviours.md section 1.4.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from typing import Annotated, Any

from pydantic import AfterValidator, BeforeValidator

#: The canonical form: what this server emits, always.
CANONICAL = re.compile(r"\A[0-9a-f]{32}\Z")

#: What this server accepts: the canonical form, the dashed form, either with optional braces, in
#: any casing. Anything else is not an identifier.
_ACCEPTED = re.compile(
    r"\A\{?([0-9a-fA-F]{8})-?([0-9a-fA-F]{4})-?([0-9a-fA-F]{4})-?"
    r"([0-9a-fA-F]{4})-?([0-9a-fA-F]{12})\}?\Z"
)

_LENGTH_BYTES = 16


def new_id() -> str:
    """A fresh identifier, for the few things that are generated rather than derived."""
    return secrets.token_hex(_LENGTH_BYTES)


def derive(*parts: str) -> str:
    """A stable identifier from stable inputs. The same parts always give the same identifier.

    Parts are joined with a NUL, which cannot occur in any of them, so no two different tuples can
    concatenate to the same key - `("a", "bc")` and `("ab", "c")` are different inputs and get
    different identifiers.

    SHA-256 truncated to sixteen bytes, for the 32-character shape clients expect.
    """
    if not parts:
        raise ValueError("derive() needs at least one part; an identifier from nothing is not one")
    key = b"\0".join(part.encode("utf-8") for part in parts)
    return hashlib.sha256(key).digest()[:_LENGTH_BYTES].hex()


def normalise(value: Any) -> Any:
    """Canonicalise anything the reference would parse; leave the rest for pydantic to reject."""
    if not isinstance(value, str):
        return value
    match = _ACCEPTED.match(value.strip())
    if match is None:
        return value
    return "".join(match.groups()).lower()


def require_canonical(value: str) -> str:
    """Reject anything that is not an identifier, saying what one looks like.

    A pattern constraint would produce "String should match pattern
    '\\A[0-9a-f]{32}\\Z'", which tells a reader what was wanted only if they can read a regular
    expression under time pressure.
    """
    if CANONICAL.match(value) is None:
        raise ValueError(
            f"{value!r} is not an identifier. Expected 32 hexadecimal characters, optionally "
            f"dashed or braced, such as 0d41983a5d18d53282f56e7460e2c2cd."
        )
    return value


#: The type every identifier-valued field uses. Lenient in, canonical out.
WireGuid = Annotated[str, BeforeValidator(normalise), AfterValidator(require_canonical)]

__all__ = ["CANONICAL", "WireGuid", "derive", "new_id", "normalise", "require_canonical"]
