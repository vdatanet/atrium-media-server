# SPDX-License-Identifier: GPL-3.0-or-later
"""How a response body is escaped, which is not how Python escapes it.

The reference is an ASP.NET Core application and its serialiser uses the HTML-safe
`JavaScriptEncoder`: every non-ASCII character and seven ASCII ones go out as `\\uXXXX` with
**uppercase** hex. Python writes both literally.

**No client can tell** - a JSON parser decodes the two forms to the same string - so this is not
Principle I. It is Principle VIII: the goldens compare bytes, and a library with accented titles
would otherwise differ from the reference on nearly every response while being correct in every
field.

The measurement that produced the escape set is worth repeating. Item names only ever proved what
the corpus happened to contain; the exact set came from echoing arbitrary characters through a
validation error, which is the one route that puts client text in a response body.
`[probe: tools/probe_query_envelope.py, Jellyfin 10.11.11, 2026-08-28]`
"""

from __future__ import annotations

import json

import pytest

from atrium.compat.responses import AtriumJSONResponse


def rendered(payload: object) -> str:
    return AtriumJSONResponse.render(None, payload).decode("utf-8")


@pytest.mark.parametrize(
    ("character", "escape"),
    [
        ("&", "\\u0026"),
        ("'", "\\u0027"),
        ("+", "\\u002B"),
        ('"', "\\u0022"),
        ("<", "\\u003C"),
        (">", "\\u003E"),
        ("`", "\\u0060"),
        ("ñ", "\\u00F1"),
        ("é", "\\u00E9"),
        ("ç", "\\u00E7"),
    ],
)
def test_each_measured_character_is_escaped_the_references_way(character: str, escape: str) -> None:
    assert rendered({"n": character}) == '{"n":"' + escape + '"}'


@pytest.mark.parametrize("character", ["/", "=", ":", " ", "!", "*", "(", ")", "-", "_"])
def test_a_character_the_reference_leaves_alone_is_left_alone(character: str) -> None:
    """Measured in the same request: `/`, `=`, `:` and the space came back literal. Escaping more
    than the reference does is as much a byte difference as escaping less."""
    assert rendered({"n": character}) == '{"n":"' + character + '"}'


def test_the_hex_is_uppercase() -> None:
    """`\\u00F1`, not `\\u00f1`. Python's own `ensure_ascii=True` produces lowercase, which is a
    difference on every accented character in the library."""
    body = rendered({"n": "años"})
    assert "\\u00F1" in body
    assert "\\u00f1" not in body


def test_a_literal_backslash_u_in_the_data_is_not_uppercased() -> None:
    """The case that makes this a parity problem rather than a search-and-replace. A *value*
    containing the six characters `\\u00e9` must survive as those six characters; only the
    encoder's own escapes are rewritten."""
    body = rendered({"n": "not an escape: \\u00e9"})
    assert body == '{"n":"not an escape: \\\\u00e9"}'
    assert json.loads(body)["n"] == "not an escape: \\u00e9"


def test_a_windows_path_survives() -> None:
    body = rendered({"p": "C:\\films\\a"})
    assert json.loads(body)["p"] == "C:\\films\\a"


def test_the_body_round_trips_to_what_went_in() -> None:
    """The whole justification: the bytes differ from Python's default and the *value* does not.
    A client parses the same thing either way, which is why this is not a delta in either
    direction."""
    payload = {
        "Name": '28 años después: Abraham\'s & <b> `x` + "q"',
        "Nested": [{"Overview": "Ünicode — em dash, ellipsis…"}],
    }
    assert json.loads(rendered(payload)) == payload


def test_the_separators_are_compact() -> None:
    """`{"a":1,"b":2}` - measured, no spaces. Starlette's default already agrees; asserted because
    the override could have lost it."""
    assert rendered({"a": 1, "b": 2}) == '{"a":1,"b":2}'
