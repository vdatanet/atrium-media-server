# SPDX-License-Identifier: GPL-3.0-or-later
"""The JSON response class every route returns.

The reference is an ASP.NET Core application, and its JSON formatter emits

    Content-Type: application/json; charset=utf-8

Starlette appends `charset=utf-8` only to `text/*` media types, so its `JSONResponse` sends a bare
`application/json`. That is a difference on **every** response in the project, and one nobody would
find by reading either codebase - it took looking at real traffic.
`[probe: tools/probe_routing.py, Jellyfin 10.11.11, 2026-08-28]`

**And the content type says which serialisation was used.** The reference accepts
`application/json; profile="PascalCase"` and `profile="CamelCase"`, answers the second in
camelCase, and echoes whichever profile matched - before the charset, canonically spelled - on
every JSON response, a bare string body included.
`[probe: tools/probe_content_type_profiles.py, Jellyfin 10.11.11, 2026-08-26]`

So the media type is per response rather than per class: it is read from the profile negotiated
for the request being served. `atrium.compat.profiles` decides that, and `AtriumModel` applies it
to the body - which is the only place a property name can be told apart from a dictionary key.

A refusal carries no content type at all, in the reference and here, so it echoes nothing: an
empty `401`, `404` or `405` is built by `atrium.compat.errors`, not by this class.

**And the bytes inside the body are escaped the reference's way**, which is not Python's. See
`ESCAPED` and `render` below, and behaviours section 1.16.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from fastapi.responses import JSONResponse
from starlette.background import BackgroundTask

from atrium.compat.profiles import JSON_MEDIA_TYPE, current

#: ASCII characters the reference escapes as `\uXXXX` even though JSON does not require it, and
#: which are never JSON structure - so they can be replaced across the whole document safely.
#: Measured by echoing them through a validation error, which is the one route that puts arbitrary
#: client text in a response body.
#: `[probe: tools/probe_query_envelope.py, Jellyfin 10.11.11, 2026-08-28]` (behaviours section 1.16)
ESCAPED: Mapping[int, str] = {
    ord("&"): "\\u0026",
    ord("'"): "\\u0027",
    ord("+"): "\\u002B",
    ord("<"): "\\u003C",
    ord(">"): "\\u003E",
    ord("`"): "\\u0060",
}

#: A `\uXXXX` the encoder produced, as opposed to the literal characters `\u00e9` inside a string.
#: The leading group matches an even number of backslashes, which is what tells the two apart:
#: every literal backslash in data has already been doubled by `json.dumps`.
_ENCODER_ESCAPE = re.compile(r"(?<!\\)((?:\\\\)*)\\u([0-9a-f]{4})")

#: The same parity trick for a data quote, which `json.dumps` writes as `\"` and the reference
#: writes as `\u0022`.
_ENCODER_QUOTE = re.compile(r'(?<!\\)((?:\\\\)*)\\"')


class AtriumJSONResponse(JSONResponse):
    """`JSONResponse` with the reference's exact content type, profile and all."""

    media_type = JSON_MEDIA_TYPE

    def __init__(
        self,
        content: Any = None,
        status_code: int = 200,
        headers: Mapping[str, str] | None = None,
        media_type: str | None = None,
        background: BackgroundTask | None = None,
    ) -> None:
        """The parameters are spelled out, and that is not decoration.

        FastAPI builds the OpenAPI document by **inspecting this signature** for a `status_code`
        parameter with an integer default, and uses it as the operation's success status. Written
        as `*args, **kwargs` - which is otherwise the obvious way to add one default - the
        parameter disappears from the signature and generating the document raises
        `UnboundLocalError`. A test asserts the document still builds, which is the only reason
        that was a five-minute problem rather than a release-day one.
        """
        # The negotiated profile applies only when the caller did not decide for itself. The
        # framework constructs these without a media type, which is what makes the negotiated one
        # the default rather than something every route has to remember to pass.
        super().__init__(
            content, status_code, headers, media_type or current().media_type, background
        )

    def render(self, content: Any) -> bytes:
        r"""The body, escaped the way the reference escapes it.

        The reference is an ASP.NET Core application and its serialiser uses the **HTML-safe**
        `JavaScriptEncoder`, which escapes every non-ASCII character and seven ASCII ones as
        `\uXXXX` with **uppercase** hex. `28 años después` goes out as `28 a\u00F1os despu\u00E9s`
        and `Abraham\u0027s Boys` keeps its apostrophe escaped. Python writes both literally.

        No client can tell: a JSON parser decodes the two forms to the same string, so Principle I
        does not require this. What requires it is Principle VIII - the goldens compare **bytes**,
        and a library with accented titles would otherwise differ from the reference on nearly
        every response while being correct in every field. Reproducing it here, once, is cheaper
        than an asterisk on every golden.

        `[probe: tools/probe_query_envelope.py, Jellyfin 10.11.11, 2026-08-28]`
        (behaviours section 1.16)
        """
        text = json.dumps(
            content, ensure_ascii=True, allow_nan=False, indent=None, separators=(",", ":")
        )
        text = _ENCODER_ESCAPE.sub(lambda m: m.group(1) + "\\u" + m.group(2).upper(), text)
        text = _ENCODER_QUOTE.sub(lambda m: m.group(1) + "\\u0022", text)
        return text.translate(dict(ESCAPED)).encode("utf-8")


__all__ = ["ESCAPED", "JSON_MEDIA_TYPE", "AtriumJSONResponse"]
